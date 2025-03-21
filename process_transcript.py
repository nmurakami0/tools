import argparse
import os
import time

from openai import OpenAI


def split_text_by_conversation(text, max_chars=10000):
    """Split text into chunks while preserving conversation boundaries."""
    chunks = []
    current_chunk = []
    current_length = 0

    # Split by lines to preserve conversation structure
    lines = text.split('\n')

    for line in lines:
        # If adding this line would exceed the limit
        if current_length + len(line) + 1 > max_chars and current_chunk:  # +1 for newline
            # Join current chunk and add to chunks
            chunks.append('\n'.join(current_chunk))
            # Start new chunk with current line
            current_chunk = [line]
            current_length = len(line)
        else:
            # Add line to current chunk
            current_chunk.append(line)
            current_length += len(line) + 1  # +1 for newline

    # Add the last chunk if it's not empty
    if current_chunk:
        chunks.append('\n'.join(current_chunk))

    return chunks

def process_chunk(client, chunk):
    """Process a single chunk of text using OpenAI API."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # 4k-mini model
            messages=[
                {"role": "system", "content": "自然な文章に修正してください。ただし、会議の文字起こしなので極力元の会話を再現してください。"},
                {"role": "user", "content": chunk}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error processing chunk: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description='Process transcribed text using OpenAI API')
    parser.add_argument('input_file', help='Path to the input transcription file')
    parser.add_argument('output_file', help='Path to save the processed output')
    parser.add_argument('--api-key', help='OpenAI API key (optional, defaults to environment variable)')

    args = parser.parse_args()

    # Get API key from argument or environment variable
    api_key = args.api_key or os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OpenAI API key must be provided either through --api-key argument or OPENAI_API_KEY environment variable")

    # Initialize OpenAI client
    client = OpenAI(api_key=api_key)

    try:
        # Read input file
        with open(args.input_file, 'r', encoding='utf-8') as f:
            text = f.read()

        # Split text into chunks
        chunks = split_text_by_conversation(text)

        # Process each chunk
        processed_chunks = []
        for i, chunk in enumerate(chunks):
            print(f"Processing chunk {i+1}/{len(chunks)}...")

            # Add delay between requests to respect rate limits
            if i > 0:
                time.sleep(1)

            result = process_chunk(client, chunk)
            if result:
                processed_chunks.append(result)
            else:
                print(f"Warning: Chunk {i+1} processing failed, using original text")
                processed_chunks.append(chunk)

        # Combine processed chunks and write to output file
        with open(args.output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(processed_chunks))

        print(f"Processing complete. Output written to {args.output_file}")

    except FileNotFoundError:
        print(f"Error: Input file '{args.input_file}' not found")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    main()
