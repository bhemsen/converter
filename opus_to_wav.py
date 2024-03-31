import os
import argparse
import multiprocessing
import sys
import time
from pydub import AudioSegment
from tqdm import tqdm

class FileConverter:
    def __init__(self, input_dir, output_dir):
        self.input_dir = input_dir
        self.output_dir = output_dir
    
    def convert_opus_to_wav(self, opus_file):
        # Load the .opus file
        audio = AudioSegment.from_file(opus_file, codec="opus")

        # Create the output directory if it doesn't exist
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        
        # Create the output filename
        filename = os.path.basename(opus_file)
        output_filename = os.path.splitext(filename)[0] + ".wav"
        wav_file = os.path.join(self.output_dir, output_filename)
        
        # Export the audio to .wav format
        audio.export(wav_file, format="wav")

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
    parser = argparse.ArgumentParser(description="Convert .opus files to .wav.")
    parser.add_argument("input_dir", help="Input directory containing .opus files")
    parser.add_argument("output_dir", help="Output directory to save .wav files")
    args = parser.parse_args()
    
    converter = FileConverter(args.input_dir, args.output_dir)
    
    # Get list of .opus files
    opus_files = [os.path.join(args.input_dir, filename) for filename in os.listdir(args.input_dir) if filename.endswith(".opus")]
    
    # Set up progress tracking
    total_files = len(opus_files)
    with tqdm(total=total_files, desc="Progress", unit="file") as pbar:
        # Start loading animation
        done_event = multiprocessing.Event()
        loading_thread = multiprocessing.Process(target=loading_animation, args=(done_event,))
        loading_thread.start()

        # Run conversions simultaneously using multiprocessing
        processes = []
        for opus_file in opus_files:
            process = multiprocessing.Process(target=converter.convert_opus_to_wav, args=(opus_file,))
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
