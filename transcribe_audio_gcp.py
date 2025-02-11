import argparse
import os
import uuid

from google.cloud import speech, storage


def transcribe_audio(file_path, output_path=None, credentials_path=None, bucket_name=None):
    """
    Transcribe an audio file using Google Cloud Speech-to-Text API.

    Args:
        file_path (str): Path to the audio file
        output_path (str, optional): Path to save the transcription. If not provided, only returns the text
        credentials_path (str, optional): Path to GCP service account key JSON file.
            If not provided, will look for GOOGLE_APPLICATION_CREDENTIALS env variable
        bucket_name (str, optional): Name of the GCS bucket to use. If not provided, will look for
            GOOGLE_CLOUD_BUCKET env variable

    Returns:
        str: Transcribed text
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    # Set credentials if provided
    if credentials_path:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
    elif not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        raise ValueError("GCP credentials not found. Please provide credentials_path or set GOOGLE_APPLICATION_CREDENTIALS environment variable")

    # Get bucket name
    bucket_name = bucket_name or os.getenv("GOOGLE_CLOUD_BUCKET")
    if not bucket_name:
        raise ValueError("GCS bucket not specified. Please provide bucket_name or set GOOGLE_CLOUD_BUCKET environment variable")

    # Initialize clients
    storage_client = storage.Client()
    speech_client = speech.SpeechClient()

    try:
        # Upload file to GCS
        bucket = storage_client.bucket(bucket_name)
        blob_name = f"audio_transcription/{str(uuid.uuid4())}{os.path.splitext(file_path)[1]}"
        blob = bucket.blob(blob_name)

        print("Uploading audio file to Google Cloud Storage...")
        blob.upload_from_filename(file_path)
        gcs_uri = f"gs://{bucket_name}/{blob_name}"

        try:
            print("Transcribing audio file...")
            audio = speech.RecognitionAudio(uri=gcs_uri)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.MP3,
                sample_rate_hertz=44100,  # Adjust based on your audio file
                language_code="ja-JP",
                enable_automatic_punctuation=True,
            )

            # Start long-running recognition operation
            operation = speech_client.long_running_recognize(config=config, audio=audio)
            print("Waiting for operation to complete...")
            response = operation.result(timeout=6000)

            transcribed_text = ""
            for result in response.results:
                transcribed_text += result.alternatives[0].transcript + "\n"

            if output_path:
                output_dir = os.path.dirname(output_path)
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(transcribed_text)

            return transcribed_text.strip()

        finally:
            # Clean up: delete the file from GCS
            print("Cleaning up: deleting file from Google Cloud Storage...")
            blob.delete()

    except Exception as e:
        raise Exception(f"Error during transcription: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description='Transcribe audio file using Google Cloud Speech-to-Text')
    parser.add_argument('file_path', help='Path to the audio file')
    parser.add_argument('-o', '--output', help='Path to save the transcription (optional)')
    parser.add_argument('--credentials', help='Path to GCP service account key JSON file (optional if GOOGLE_APPLICATION_CREDENTIALS env variable is set)')
    parser.add_argument('--bucket', help='GCS bucket name (optional if GOOGLE_CLOUD_BUCKET env variable is set)')
    args = parser.parse_args()

    try:
        transcription = transcribe_audio(args.file_path, args.output, args.credentials, args.bucket)
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
