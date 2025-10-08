import os

class MyProcessor:
    def __init__(self):
        self.data = []

    def load_data(self, path):
        with open(path, 'r') as f:
            self.data = f.readlines()
    
    def deprecated_method(self):
        print("This should be removed.")

def helper_function():
    pass