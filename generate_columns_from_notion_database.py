import argparse
import csv
import re

parser = argparse.ArgumentParser(description='Generate columns from mermaid')
parser.add_argument('--input_file', '-i', type=str, help='input file path')
parser.add_argument('--output_file', '-o', type=str, help='output file path')
args = parser.parse_args()


with open(args.input_file, newline='') as f:
    reader = csv.reader(f, delimiter=',')
    header = next(reader)
    rows = []
    for row in reader:
        logical_name = row[0]
        component_type = row[1].split(' ')[0]
        format = row[3].split(' ')[0]
        size = row[4]
        rows.append(','.join([logical_name, component_type, format, size]))

with open(args.output_file, 'w') as f:
    for row in rows:
        f.write(f'{row}\n')
