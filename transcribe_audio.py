import argparse
import math
import os
from pathlib import Path
from typing import List

from moviepy.audio.io.AudioFileClip import AudioFileClip
from openai import OpenAI
from pydub import AudioSegment


def split_audio(file_path: str, chunk_size_mb: int = 24) -> List[str]:
    """
    Split an audio file into smaller chunks.

    Args:
        file_path (str): Path to the audio file
        chunk_size_mb (int): Maximum size of each chunk in MB

    Returns:
        List[str]: List of paths to the chunk files
    """
    # Get file extension
    _, ext = os.path.splitext(file_path)

    # Load audio file
    audio = AudioSegment.from_file(file_path)

    # Calculate chunk duration based on file size and total duration
    file_size = os.path.getsize(file_path)
    audio_clip = AudioFileClip(file_path)
    duration = audio_clip.duration
    audio_clip.close()

    # Calculate chunk duration to achieve desired chunk size
    chunk_duration = (chunk_size_mb * 1024 * 1024 * duration) / file_size
    chunk_duration_ms = int(chunk_duration * 1000)  # Convert to milliseconds

    # Create chunks directory
    base_dir = os.path.dirname(file_path)
    chunks_dir = os.path.join(base_dir, "audio_chunks")
    os.makedirs(chunks_dir, exist_ok=True)

    chunk_paths = []
    for i, chunk_start in enumerate(range(0, len(audio), chunk_duration_ms)):
        chunk = audio[chunk_start:chunk_start + chunk_duration_ms]
        chunk_path = os.path.join(chunks_dir, f"chunk_{i}{ext}")
        chunk.export(chunk_path, format=ext[1:])  # Remove dot from extension
        chunk_paths.append(chunk_path)

    return chunk_paths

def transcribe_audio(file_path, output_path=None, api_key=None):
    """
    Transcribe an audio file using OpenAI's Whisper model.

    Args:
        file_path (str): Path to the audio file
        output_path (str, optional): Path to save the transcription. If not provided, only returns the text
        api_key (str, optional): OpenAI API key. If not provided, will look for OPENAI_API_KEY env variable

    Returns:
        str: Transcribed text
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    # Get API key from environment if not provided
    api_key = api_key or os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OpenAI API key not found. Please provide it as an argument or set OPENAI_API_KEY environment variable")

    client = OpenAI(api_key=api_key)

    try:
        # Split audio if file is too large (>25MB)
        if os.path.getsize(file_path) > 25 * 1024 * 1024:
            print("Audio file is larger than 25MB. Splitting into chunks...")
            chunk_paths = split_audio(file_path)
            transcribed_text = ""

            for i, chunk_path in enumerate(chunk_paths):
                print(f"Processing chunk {i+1}/{len(chunk_paths)}...")
                with open(chunk_path, "rb") as audio_file:
                    transcript = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file
                    )
                    transcribed_text += transcript.text + "\n"

                # Clean up chunk
                os.remove(chunk_path)

            # Remove chunks directory if empty
            chunks_dir = os.path.dirname(chunk_paths[0])
            if not os.listdir(chunks_dir):
                os.rmdir(chunks_dir)
        else:
            # Process single file if size is acceptable
            with open(file_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file
                )
                transcribed_text = transcript.text

        if output_path:
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(transcribed_text)

        return transcribed_text
    except Exception as e:
        raise Exception(f"Error during transcription: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description='Transcribe audio file using OpenAI Whisper')
    parser.add_argument('file_path', help='Path to the audio file')
    parser.add_argument('-o', '--output', help='Path to save the transcription (optional)')
    parser.add_argument('--api-key', help='OpenAI API key (optional if OPENAI_API_KEY env variable is set)')
    args = parser.parse_args()

    try:
        transcription = transcribe_audio(args.file_path, args.output, args.api_key)
        print("Transcription completed successfully")
        if args.output:
            print(f"Transcription saved to: {args.output}")
        else:
            print("Transcription:")
            print(transcription)
    except Exception as e:
        print(f"Error: {str(e)}")
        exit(1)

if __name__ == "__main__":
    main()
