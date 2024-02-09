import argparse
import csv
import os

import inflection
from openai import OpenAI

API_KEY = os.environ["OPENAI_API_KEY"]
client = OpenAI(
    api_key=API_KEY,
    organization='org-yQqX8paIy5c7VRHlOdno8RQ3'
)

parser = argparse.ArgumentParser(description='Generate columns from mermaid')
parser.add_argument('--input_file', '-i', type=str, help='input file path')
parser.add_argument('--output_file', '-o', type=str, help='output file path')
parser.add_argument('--source_col_index', '-s', type=int, help='source column index')
parser.add_argument('--target_col_index', '-t', type=int, help='target column index')
args = parser.parse_args()

def translate_japanese_to_english_snake_case(input_csv_path, source_col_index, target_col_index, output_csv_path):
    with open(input_csv_path, mode='r', encoding='utf-8') as infile, open(output_csv_path, mode='w', encoding='utf-8', newline='') as outfile:
        reader = csv.reader(infile)
        writer = csv.writer(outfile)

        header = next(reader)
        writer.writerow(header)

        translated_dict = {}
        for row in reader:
            japanese_text = row[source_col_index]
            print(row)
            if row[target_col_index] != '':
                writer.writerow(row)
                continue
            if japanese_text in translated_dict:
                translation = translated_dict[japanese_text]
            else:
                messages = [{"role": "system", "content": f"Translate this Japanese text to English in snake case: '{japanese_text}'"}]
                completion = client.chat.completions.create(
                     model="gpt-4",
                     messages=messages,
                )
                translation = completion.choices[0].message.content
                translated_dict[japanese_text] = translation
                print(f"Translated '{japanese_text}' to '{translation}'")
            translation_snake_case = inflection.underscore(translation)

            if len(row) <= target_col_index:
                row += [''] * (target_col_index + 1 - len(row))
            row[target_col_index] = translation_snake_case
            writer.writerow(row)



# スクリプトを実行
translate_japanese_to_english_snake_case(args.input_file, args.source_col_index, args.target_col_index, args.output_file)
