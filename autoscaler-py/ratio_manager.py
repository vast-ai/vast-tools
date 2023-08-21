def update_rolling_average(prev_avg, new_avg, time_elapsed, m):
    weight = 0.5 ** (m * time_elapsed)
    x = weight*prev_avg + (1-weight)*new_avg
    return x

