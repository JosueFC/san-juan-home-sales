"""Batch-process copied property pages using parse_real_estate.py.

Run from project root:
    python scr/batch_parse_real_estate.py --input-dir data/raw --output data/processed/properties.csv

Keep source pages private and only process materials you have permission to use.
"""
import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_real_estate import parse


def natural_key(path):
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r'(\d+)', path.name)]


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        # Remove a stale file from an earlier run so an old report is never mistaken for a current one.
        path.unlink(missing_ok=True)
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def load_overrides(path):
    """{property_id: {field: float}} from a CSV with columns property_id, field, value. Optional file."""
    result = {}
    if path.exists():
        with path.open(encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                if row.get('property_id') and row.get('field') and row.get('value', '').strip():
                    result.setdefault(row['property_id'].strip(), {})[row['field'].strip()] = float(row['value'].replace(',', ''))
        print(f'Loaded {sum(len(v) for v in result.values())} manual overrides from {path}')
    return result


def main():
    ap = argparse.ArgumentParser(description='Parse and combine all property .txt pages')
    ap.add_argument('--input-dir', type=Path, default=Path('data/raw'))
    ap.add_argument('--output', type=Path, default=Path('data/processed/properties.csv'))
    ap.add_argument('--overrides', type=Path, default=Path('data/overrides.csv'),
                    help='optional CSV with columns property_id,field,value for manual corrections (e.g. gla_sqft)')
    args = ap.parse_args()
    overrides = load_overrides(args.overrides)

    if not args.input_dir.is_dir():
        ap.error(f'Input folder does not exist: {args.input_dir}')
    files = sorted(args.input_dir.glob('*.txt'), key=natural_key)
    if not files:
        ap.error(f'No .txt files found in {args.input_dir}')

    rows, failures, empty_files = [], [], []
    failed_files = bad_rows = 0
    for file in files:
        try:
            parsed = list(parse(file.read_text(encoding='utf-8-sig'), file.name, overrides))
            if not parsed:
                empty_files.append(file.name)
            rows.extend(parsed)
            print(f'{file.name}: {len(parsed)} records')
        except Exception as exc:
            failed_files += 1
            failures.append({'source_file': file.name, 'error': str(exc)})
            print(f'ERROR {file.name}: {exc}')

    # Keep the first occurrence in the primary CSV. A record is a duplicate if its property_id OR its
    # dedup_key (catastro + contract date, or a registry fallback) was already seen. All duplicates are
    # written to duplicate_records.csv with the property_id they matched, for manual review.
    by_id, by_key, unique, duplicates = {}, {}, [], []
    for row in rows:
        pid = row.get('property_id')
        if not pid:
            bad_rows += 1
            failures.append({'source_file': row.get('source_file', ''), 'error': 'Missing property_id'})
            continue
        key = row.get('dedup_key') or ''
        kept = by_id.get(pid) or (by_key.get(key) if key else None)
        if kept:
            row['duplicate_of'] = kept['property_id']
            row['duplicate_reason'] = 'same property_id' if pid in by_id else 'same dedup_key'
            duplicates.append(row)
        else:
            by_id[pid] = row
            if key:
                by_key[key] = row
            unique.append(row)

    write_csv(args.output, unique)
    write_csv(args.output.with_name('duplicate_records.csv'), duplicates)
    write_csv(args.output.with_name('parse_errors.csv'), failures)
    if empty_files:
        print('No records found in: ' + ', '.join(empty_files))
    print(f'\nFiles: {len(files)} | Raw records: {len(rows)} | Unique: {len(unique)}'
          f' | Duplicates: {len(duplicates)}')
    print(f'Failed files: {failed_files} | Rows without property_id: {bad_rows}')
    print(f'Combined CSV: {args.output}')
    if duplicates:
        print('Review duplicate_records.csv for conflicting values before treating the first row as authoritative.')
    print(f'Missing living area: {sum(not r.get("gla_sqft") for r in unique)}')
    print(f'Contract price differs from sales price: '
          f'{sum(r.get("contract_matches_sales_price") == 0 for r in unique)}')
    flag_counts = Counter(f for r in unique for f in r.get('quality_flags', '').split(';') if f)
    if flag_counts:
        print('Quality flags: ' + ', '.join(f'{k}={v}' for k, v in flag_counts.most_common()))


if __name__ == '__main__':
    main()