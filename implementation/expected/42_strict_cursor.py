# Test file for strict cursor logic.
# The patch should fail because it tries to find "Line at top"
# *after* it has already modified "Unique Line".

print("Line at top")

def main():
    print("Unique Line")

print("Line at bottom")