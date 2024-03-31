import os
import argparse
import multiprocessing
import sys
import time
from tqdm import tqdm
import ffmpeg

class FileConverter:
    def __init__(self, input_dir, output_dir):
        self.input_dir = input_dir
        self.output_dir = output_dir
    
    def convert_mkv_to_mp4(self, mkv_file):
        # Create the output directory if it doesn't exist
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        
        # Create the output filename
        filename = os.path.basename(mkv_file)
        output_filename = os.path.splitext(filename)[0] + ".mp4"
        mp4_file = os.path.join(self.output_dir, output_filename)
        
        # Use ffmpeg-python to convert MKV to MP4
        (
            ffmpeg
            .input(mkv_file)
            .output(mp4_file)
            .run()
        )

def loading_animation(done_event):
    while not done_event.is_set():
        sys.stdout.write('\rProcessing... |')
        time.sleep(0.1)
        sys.stdout.write('\rProcessing... /')
        time.sleep(0.1)
        sys.stdout.write('\rProcessing... -')
        time.sleep(0.1)
        sys.stdout.write('\rProcessing... \\')
        time.sleep(0.1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert .mkv files to .mp4.")
    parser.add_argument("input_dir", help="Input directory containing .mkv files")
    parser.add_argument("output_dir", help="Output directory to save .mp4 files")
    args = parser.parse_args()
    
    converter = FileConverter(args.input_dir, args.output_dir)
    
    # Get list of .mkv files
    mkv_files = [os.path.join(args.input_dir, filename) for filename in os.listdir(args.input_dir) if filename.endswith(".mkv")]
    
    # Set up progress tracking
    total_files = len(mkv_files)
    with tqdm(total=total_files, desc="Progress", unit="file") as pbar:
        # Start loading animation
        done_event = multiprocessing.Event()
        loading_thread = multiprocessing.Process(target=loading_animation, args=(done_event,))
        loading_thread.start()

        # Run conversions simultaneously using multiprocessing
        processes = []
        for mkv_file in mkv_files:
            process = multiprocessing.Process(target=converter.convert_mkv_to_mp4, args=(mkv_file,))
            processes.append(process)
            process.start()
        
        # Wait for conversions to complete
        for process in processes:
            process.join()
            pbar.update(1)  # Update progress bar
        
        # Stop loading animation
        done_event.set()
        loading_thread.join()
        
        print("\nConversion completed.")
