import argparse
import re


def parse_text(target_string: str) -> (str, str):
    pattern = re.compile(r'[^"]*"(?P<logical_name>[^(]+)\s*\((?P<physical_name>[^)]+)\)" {')
    result = pattern.search(target_string)
    if result is None:
        return None
    return (result.group('physical_name'), result.group('logical_name'))

parser = argparse.ArgumentParser(description='Generate columns from mermaid')
parser.add_argument('--input_file', '-i', type=str, help='input file path')
parser.add_argument('--output_file', '-o', type=str, help='output file path')
args = parser.parse_args()

names = []

with open(args.input_file, 'r') as f:
  for line in f:
      parsed = parse_text(line)
      if parsed is not None:
        names.append(parsed)
table_dict = dict(names)

with open(args.output_file, 'w') as f:
   for key, value in table_dict.items():
         f.write(f'{key}, {value}\n')
