"""Shared utilities for WBB comeback probability analysis."""


def bin_deficit(deficit):
    """Assign deficit to a bucket label."""
    if deficit <= 10:
        return str(int(deficit))
    elif deficit <= 15:
        return "11-15"
    elif deficit <= 20:
        return "16-20"
    elif deficit <= 25:
        return "21-25"
    elif deficit <= 30:
        return "26-30"
    else:
        return "31+"


def bin_deficit_sort_key(label):
    """Sort key for deficit bucket labels."""
    if label.isdigit():
        return int(label)
    elif label == "31+":
        return 31
    else:
        return int(label.split("-")[0])


# Alias for convenience
deficit_sort_key = bin_deficit_sort_key


def time_bucket_label(seconds_remaining):
    """Assign time remaining to a bucket label.

    Returns 30-second bins for the final 2 minutes (0-120 seconds),
    and 1-minute bins for 2-39 minutes.
    """
    minutes = seconds_remaining / 60.0
    if minutes < 2.0:
        # 30-second bins: "0.0-0.5", "0.5-1.0", "1.0-1.5", "1.5-2.0"
        half_min = int(minutes * 2)
        half_min = min(half_min, 3)  # cap at 1.5-2.0
        lower = half_min * 0.5
        upper = lower + 0.5
        return f"{lower:.1f}-{upper:.1f}"
    else:
        bucket = min(int(minutes), 39)
        return str(bucket)


def time_bucket_sort_key(label):
    """Sort key for time bucket labels (handles both '0.0-0.5' and '3' formats)."""
    if "-" in label:
        return float(label.split("-")[0])
    return float(label)
