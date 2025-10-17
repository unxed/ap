def complex_calculation(data):
    # This is a long and complex function
    # where we want to replace a large internal block.

    # Stage 1: Pre-processing
    processed_data = []
    for item in data:
        if item.is_valid():
            processed_data.append(item.process())

    # Stage 2: Core logic (this whole block will be replaced)
    # It has multiple lines and comments.
    # Replacing it with a single snippet would be fragile.
    # Let's simulate some complex code.
    intermediate_result = 0
    for val in processed_data:
        intermediate_result += val * 1.1
    result = intermediate_result / len(processed_data)

    # Stage 3: Post-processing
    return f"Final result: {result}"
