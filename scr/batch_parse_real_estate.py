"""Batch-process copied property pages using parse_real_estate.py.

Run from project root:
    python batch_parse_real_estate.py --input-dir data/raw --output data/processed/properties.csv

Keep source pages private and only process materials you have permission to use.
"""
import argparse
import csv
import re
from collections import Counter
from pathlib import Path
from parse_real_estate import parse


def natural_key(path):
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r'(\d+)', path.name)]


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description='Parse and combine all property .txt pages')
    ap.add_argument('--input-dir', type=Path, default=Path('data/raw'))
    ap.add_argument('--output', type=Path, default=Path('data/processed/properties.csv'))
    args = ap.parse_args()

    if not args.input_dir.is_dir():
        ap.error(f'Input folder does not exist: {args.input_dir}')
    files = sorted(args.input_dir.glob('*.txt'), key=natural_key)
    if not files:
        ap.error(f'No .txt files found in {args.input_dir}')

    rows, failures, empty_files = [], [], []
    for file in files:
        try:
            parsed = list(parse(file.read_text(encoding='utf-8-sig')))
            if not parsed:
                empty_files.append(file.name)
            for row in parsed:
                row['source_file'] = file.name
                rows.append(row)
            print(f'{file.name}: {len(parsed)} records')
        except Exception as exc:
            failures.append({'source_file': file.name, 'error': str(exc)})
            print(f'ERROR {file.name}: {exc}')

    # Keep the first occurrence in the primary CSV; separately preserve and report all duplicates.
    seen, unique, duplicates = {}, [], []
    for row in rows:
        property_id = row.get('property_id')
        if not property_id:
            failures.append({'source_file': row['source_file'], 'error': 'Missing property_id'})
            continue
        if property_id in seen:
            duplicates.append(row)
        else:
            seen[property_id] = row
            unique.append(row)

    write_csv(args.output, unique)
    write_csv(args.output.with_name('duplicate_records.csv'), duplicates)
    write_csv(args.output.with_name('parse_errors.csv'), failures)
    if empty_files:
        print('No records found in: ' + ', '.join(empty_files))
    print(f'\nFiles: {len(files)} | Raw records: {len(rows)} | Unique IDs: {len(unique)}'
          f' | Duplicate IDs: {len(duplicates)} | Failed files: {len(failures)}')
    print(f'Combined CSV: {args.output}')
    if duplicates:
        print('Review duplicate_records.csv for conflicting values before treating the first row as authoritative.')
    print(f'Missing living area: {sum(not r.get("gla_sqft") for r in unique)}')
    print(f'Price discrepancies: {sum(r.get("contract_header_mismatch") == 1 for r in unique)}')


if __name__ == '__main__':
    main()
