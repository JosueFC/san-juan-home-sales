"""Parse manually copied real-estate text pages into privacy-conscious CSV rows.

Usage: python parse_real_estate.py input.txt -o properties.csv
Only use on records you have permission to process. Raw pages can contain personal data.
"""
import argparse
import csv
import re
from pathlib import Path

HEADER = re.compile(r'^ID:\s*(\d+)\t([^\t\n]+)\t([^\t\n]*)\t?([^\t\n]*)', re.M)
MONEY = re.compile(r'\$?\s*([\d,]+(?:\.\d+)?)')
FIELDS = {
    'Municipality':'municipality', 'Latitud':'latitude', 'Longitud':'longitude',
    'Flood Zone':'flood_zone', 'GLA(feet)':'gla_sqft', 'Site(meters)':'site_sqm',
    'Rooms':'rooms', 'Bedrooms':'bedrooms', 'Bathrooms':'bathrooms',
    'Full bath':'full_baths', 'Half bath':'half_baths', 'Cons. Type':'construction_type',
    'Conditions':'condition_raw', 'Garage':'garage', 'Actual age':'actual_age',
    'Efective Age':'effective_age', 'Stories':'stories', 'Units':'units',
    'Loan Type':'loan_type', 'Occupant':'occupancy', 'Date of contract':'contract_date',
    'Contract price':'contract_price', 'Days on market':'days_on_market_raw',
    'HOA':'hoa_raw', 'Gov. Incentive':'government_incentive', 'Source':'source',
}
NUMBERS = {'gla_sqft','site_sqm','latitude','longitude','rooms','bedrooms','bathrooms','full_baths','half_baths','actual_age','effective_age','stories','units'}
AMENITIES = {'terrace':r'\bterrace\b', 'fence':r'\bfenc(?:e|es)\b',
             'porch':r'\bporch\b', 'pool':r'\bswimming pool\b',
             'generator':r'\bpower generator\b', 'laundry':r'\blaundry\b'}

def money(s):
    m = MONEY.search(s or '')
    return float(m.group(1).replace(',','')) if m else None

def parse(text):
    lines = text.splitlines()
    heads = [(i, HEADER.match(line)) for i,line in enumerate(lines) if HEADER.match(line)]
    for n,(idx,match) in enumerate(heads):
        end = heads[n+1][0] - 2 if n+1 < len(heads) else len(lines)
        # Search beginning of preceding record after its ID; trailing duplicate summary is skipped.
        block = lines[idx+1:end]
        row = {'property_id':match.group(1),'record_date':match.group(2),
               'header_price_1': money(match.group(3)), 'header_price_2':money(match.group(4)),
               'neighborhood':lines[idx-2].strip() if idx >= 2 else '',
               'property_type':lines[idx-1].strip() if idx >= 1 else ''}
        extras=[]
        for line in block:
            if line.startswith('Colaborar o pedir mas informacion') or line.startswith('Address/Unit:'):
                break
            if '\t' in line:
                key,value=line.split('\t',1)
                key=key.strip(); value=value.strip()
                if key in FIELDS:
                    row[FIELDS[key]]=value
                elif key == 'Description:':
                    extras.append(value)
            elif line.startswith('Description:'):
                extras.append(line.removeprefix('Description:').strip())
            elif line.strip():
                extras.append(line.strip())
        for key in NUMBERS:
            if key in row:
                try:row[key]=float(row[key].replace(',',''))
                except ValueError:row[key]=None
        row['contract_price'] = money(row.get('contract_price'))
        row['government_incentive'] = money(row.get('government_incentive'))
        raw_dom=row.pop('days_on_market_raw','')
        d=re.match(r'^(\d+)\s+days?',raw_dom)
        row['days_on_market']=int(d.group(1)) if d else None
        row['days_on_market_note']=raw_dom if raw_dom and not d else ''
        raw_condition=row.pop('condition_raw','')
        c=re.search(r'\bC\d\b',raw_condition); q=re.search(r'\bQ\d\b',raw_condition)
        row['condition_code']=c.group() if c else raw_condition
        row['quality_code']=q.group() if q else ''
        raw_hoa=row.pop('hoa_raw','')
        row['hoa_amount']=money(raw_hoa)
        row['hoa_frequency']='year' if 'year' in raw_hoa.lower() else 'month' if 'month' in raw_hoa.lower() else ''
        raw_extras=' '.join(extras).lower()
        for name,pattern in AMENITIES.items():
            row['has_'+name]=int(bool(re.search(pattern,raw_extras)))
        row['contract_header_mismatch']=(int(abs(row['contract_price']-row['header_price_1']) > 0.01)
             if row.get('contract_price') is not None and row.get('header_price_1') is not None else '')
        yield row

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('input', type=Path)
    ap.add_argument('-o','--output',type=Path,default=Path('properties.csv'))
    args=ap.parse_args()
    rows=list(parse(args.input.read_text(encoding='utf-8-sig')))
    columns=list(dict.fromkeys(k for row in rows for k in row))
    with args.output.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=columns)
        writer.writeheader();writer.writerows(rows)
    print(f'Parsed {len(rows)} property records into {args.output}')
    print(f'Missing GLA: {sum(not r.get("gla_sqft") for r in rows)}')
    print(f'Contract/header price mismatches: {sum(r.get("contract_header_mismatch")==1 for r in rows)}')

if __name__=='__main__':
    main()
