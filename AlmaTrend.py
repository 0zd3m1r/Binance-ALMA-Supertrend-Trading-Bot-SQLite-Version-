#!/usr/bin/env python
# -*- coding: utf-8 -*-

import numpy as np
import pandas as pd


def pine_alma(series, length, offset, sigma):
    """
    Same formula as TradingView's ta.alma:
      m = offset * (length - 1)
      s = length / sigma
      w_k = exp(- (k - m)^2 / (2 * s^2)), k = 0..length-1
      ALMA[i] = sum_k w_k * src[i - (length-1 - k)] / sum_k
    """
    series = np.asarray(series, dtype=float)

    if length <= 0 or len(series) < length:
        return np.full_like(series, np.nan, dtype=float)

    m = offset * (length - 1)
    s = length / sigma

    ks = np.arange(length, dtype=float)
    weights = np.exp(-((ks - m) ** 2) / (2.0 * (s ** 2)))
    wsum = weights.sum()

    alma_vals = np.full_like(series, np.nan, dtype=float)

    # Shift: k=0 is oldest, k=length-1 is newest
    # src index: i - (length - 1 - k)
    for i in range(length - 1, len(series)):
        window = series[i - (length - 1): i + 1]  # length = length
        alma_vals[i] = np.dot(weights, window) / wsum

    return alma_vals


def generateSupertrend(close_array, high_array, low_array,
                       sd_period, alma_period, alma_offset, alma_sigma, factor):
    """
    Calculation to match the 'Alma SD SuperTrend' from the TradingView Pinescript (v6) example exactly.
    - sd = ta.stdev(src, sdlen)
    - alma = ta.alma(src, almalen, almaoffset, almasig)
    - Band update and direction logic are identical to the st() function in Pinescript.

    Note: high_array and low_array parameters are not used in the calculation (also not used in the Pine script).
    """
    close_array = np.asarray(close_array, dtype=float)

    n = len(close_array)
    if n == 0:
        return np.array([], dtype=float)

    # ALMA and SD arrays
    alma_array = pine_alma(close_array, alma_period, alma_offset, alma_sigma)

    # Pandas rolling.std ddof=1 -> compatible with TradingView ta.stdev (sample stdev)
    sd_series = pd.Series(close_array, dtype=float).rolling(window=sd_period).std(ddof=1)
    sd_array = sd_series.to_numpy()

    # Start (first valid index)
    alma_start = np.argmax(~np.isnan(alma_array)) if np.any(~np.isnan(alma_array)) else n
    sd_start = np.argmax(~np.isnan(sd_array)) if np.any(~np.isnan(sd_array)) else n
    if alma_start == n or sd_start == n:
        return np.full_like(close_array, np.nan, dtype=float)

    start_index = max(alma_start, sd_start)

    upperband = np.full(n, np.nan, dtype=float)  # mutating band
    lowerband = np.full(n, np.nan, dtype=float)  # mutating band
    supertrend = np.full(n, np.nan, dtype=float)
    direction = np.full(n, np.nan, dtype=float)

    for i in range(start_index, n):
        alma_i = alma_array[i]
        sd_i = sd_array[i]
        if np.isnan(alma_i) or np.isnan(sd_i):
            continue

        # Basic bands
        ub_basic = alma_i + factor * sd_i
        lb_basic = alma_i - factor * sd_i

        # Previous bands
        if i > start_index and not np.isnan(upperband[i - 1]):
            prev_ub = upperband[i - 1]
        else:
            prev_ub = ub_basic  # Matches the first bar behavior of nz(upperband[1]) in Pine

        if i > start_index and not np.isnan(lowerband[i - 1]):
            prev_lb = lowerband[i - 1]
        else:
            prev_lb = lb_basic

        # Band update (same conditions as Pine)
        prev_close = close_array[i - 1] if i > 0 else np.nan

        # upperband := upperband < prevupperband or close[1] > prevupperband ? upperband : prevupperband
        if (ub_basic < prev_ub) or (not np.isnan(prev_close) and prev_close > prev_ub):
            upperband[i] = ub_basic
        else:
            upperband[i] = prev_ub

        # lowerband := lowerband > prevlowerband or close[1] < prevlowerband ? lowerband : prevlowerband
        if (lb_basic > prev_lb) or (not np.isnan(prev_close) and prev_close < prev_lb):
            lowerband[i] = lb_basic
        else:
            lowerband[i] = prev_lb

        # Direction and supertrend (identical to Pine st())
        prev_super = supertrend[i - 1] if i > 0 else np.nan
        prev_ub_mut = upperband[i - 1] if i > 0 else np.nan
        prev_lb_mut = lowerband[i - 1] if i > 0 else np.nan

        # if na(sd[1]) direction := 1
        if i - 1 < 0 or np.isnan(sd_array[i - 1]):
            direction[i] = 1
        else:
            # else if prevsupertrend == prevupperband
            if not np.isnan(prev_super) and not np.isnan(prev_ub_mut) and (prev_super == prev_ub_mut):
                # direction := close > upperband ? -1 : 1
                direction[i] = -1 if close_array[i] > upperband[i] else 1
            else:
                # else direction := close < lowerband ? 1 : -1
                direction[i] = 1 if close_array[i] < lowerband[i] else -1

        # supertrend := direction == -1 ? lowerband : upperband
        supertrend[i] = lowerband[i] if direction[i] == -1 else upperband[i]

    # Only supertrend is returned for compatibility with the main script
    return supertrend
