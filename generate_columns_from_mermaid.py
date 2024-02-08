import argparse
import re


def parse_text(target_string: str) -> None or (str, str):
    pattern = re.compile(r'[^"]*"(?P<logical_name>[^(]+)\s*\((?P<physical_name>[^)]+)\)" {')
    result = pattern.search(target_string)
    if result is None:
        return None
    return (result.group('physical_name'), result.group('logical_name'))

def mermaid_to_columns(file: str) -> [str]:
    table_name = ""
    creating_table = False
    columns = []

    with open(file, 'r') as f:
      for line in f:
        line = line.strip()
        if "-" in line or "%%" in line:
            continue
        if line.startswith('"') and '"' in line[1:]:
            t = parse_text(line)
            if t is not None:
                table_name, _ = t
            creating_table = True
        elif "}" in line:
            creating_table = False
        elif creating_table and line:
            is_required = False
            parts = line.strip().split(' ')
            data_type = parts[0]
            physical_name = parts[1]
            constraint = "None"
            if len(parts) < 3:
                continue

            if physical_name == "id":
                logical_name = "ID"
                constraint = "PK"
                column_definition = f"{table_name},{physical_name},{logical_name},{data_type},{is_required},{constraint}".strip()
                columns.append(column_definition)
                continue

            if len(parts) > 3:
                constraint = parts[2]
                logical_name = parts[3].replace('"', '')
            else:
                logical_name = parts[2].replace('"', '')

            if "*" in logical_name:
                logical_name = logical_name.replace("*", "")
                is_required = True
            column_definition = f"{table_name},{physical_name},{logical_name},{data_type},{is_required},{constraint}".strip()
            columns.append(column_definition)
    return columns


parser = argparse.ArgumentParser(description='Generate columns from mermaid')
parser.add_argument('--input_file', '-i', type=str, help='input file path')
parser.add_argument('--output_file', '-o', type=str, help='output file path')
args = parser.parse_args()

columns = mermaid_to_columns(args.input_file)

with open(args.output_file, 'w') as f:
   for column in columns:
         f.write(f'{column}\n')
