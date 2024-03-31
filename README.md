# converter

This Software is born cause of the lag of free converter software that actually works 100%. 
To run it, just clone the Repo execute the script you need depending on the files you want to convert. 

## Available Converter at the moment:

* .mkv to .mp4
* .opus to .wav

More will be added in the future

## Preperation

* Clone the repo
* Make sure the latest version of [Python 3](https://www.python.org/downloads/) is installed
* Make sure the latest version of ffmpeg is installed
    - Window:  <code> winget install ffmpeg </code>
    - Mac:  <code> brew tap homebrew-ffmpeg/ffmpeg </code>
    <code>brew install homebrew-ffmpeg/ffmpeg/ffmpeg</code>
    - Linux:  <code> sudo apt install ffmpeg </code>
    - For more Information see [Official Page](https://ffmpeg.org/download.html)
* pip install -r requirements.txt


## Run Scripts

* For .mkv files run <code>py mkv_to_mp4.py "[path/to/your/mkvdirectory]" "[your/output/path]"</code> <br>
This will convert all .mkv files in the directoy to mp4 files in the output directory
* For .opus files run <code>py opus_to_wav.py "[path/to/your/mkvdirectory]" "[your/output/path]"</code> <br>
This will convert all .opus files in the directoy to wav files in the output directory


## Contribution

Feel free to clone or fork this Project and add what ever file tpye conversion/feature you need. Just open a new branch and create a Pull Request to develop and assign it to me. 

### Commit Messages

* Short description is enough. Please be es professional

### Code

You are free to use the structure or style of coding you want, but please be as declaritive as possbile and leave comments for others to understand your thoughts. 

### Help each other

Do not be afraid to contribute. It doesn't matter which skill level you have. Here is no room for shaming.

## Legal Notice

I am not responsibly for what you do with this software. Please use it only for files you legally own. 

