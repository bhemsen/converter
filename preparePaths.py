import os

def create_output_path(input_path, output_drive):
    # Get the rest of the path after the drive
    rest_path = input_path[len(os.path.splitdrive(input_path)[0]):]
    # Remove leading backslashes if any
    rest_path = rest_path.lstrip(os.sep)
    # Join the output drive with the rest of the path
    output_path = os.path.join(output_drive, rest_path)
    return output_path

def list_all_subdirectories(directory):
    subdirectories = []
    for root, dirs, files in os.walk(directory):
        for dir in dirs:
            subdirectories.append(os.path.join(root, dir))
    return subdirectories

if __name__ == "__main__":

    input_root = input("Enter the input root directory: ")
    # Get user input for the output drive
    output_drive = input("Enter the output drive: ")

    # List all subdirectories in the input root
    input_directories = list_all_subdirectories(input_root)

    # Create input-output path pairs
    input_output_pairs = []
    for input_dir in input_directories:
        output_dir = create_output_path(input_dir, output_drive)
        input_output_pairs.append((input_dir, output_dir))

    # Print the input-output pairs
    for pair in input_output_pairs:
        print(f"Input: {pair[0]}, Output: {pair[1]}")
