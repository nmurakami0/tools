import argparse
import csv
import re


def parse_markdown_header(target_string: str) -> str:
    pattern = re.compile(r'#+ (.+)')
    match = pattern.match(target_string)
    if match:
        return match.group(1)
    else:
        return None


def parse_table_header(target_string: str) -> bool:
    pattern = re.compile(r'\| ID \| キー名 \| 名前 \|.*')
    match = pattern.match(target_string)
    if match:
        return True
    else:
        return False

parser = argparse.ArgumentParser(description='Generate columns from mermaid')
parser.add_argument('--input_file', '-i', type=str, help='input file path')
parser.add_argument('--output_file', '-o', type=str, help='output file path')
args = parser.parse_args()


with open(args.input_file, 'r') as f:
    master_name = ''
    table_name = ''
    is_table = False
    output_lines = []
    for line in f:
        parsed = parse_markdown_header(line)
        if parsed is not None:
            master_table_name = parsed
            table_name = ''
            if '(' in master_table_name:
                master_name_parts = master_table_name.split('(')
                master_name = master_name_parts[0]
                table_name = master_name_parts[1].replace(')', '')
            is_table = False
        if '| --- | --- | --- |' in line:
            continue
        if is_table and '|' in line:
            parts = line.split('|')
            parts.insert(0, master_name)
            parts.insert(1, table_name)
            output_lines.append(','.join([part.strip() for part in parts if part != '']))
        if parse_table_header(line):
            is_table = True

with open(args.output_file, 'w') as f:
    f.write('\n'.join(output_lines))
