def complex_calculation(data):
    # This is a long and complex function
    # where we want to replace a large internal block.

    # Stage 1: Pre-processing
    processed_data = []
    for item in data:
        if item.is_valid():
            processed_data.append(item.process())

    # New, simplified implementation
    result = sum(processed_data)

    # Stage 3: Post-processing
    return f"Final result: {result}"
