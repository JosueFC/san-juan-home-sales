"""Parse manually copied Tasamax pages into privacy-conscious CSV rows (v2).

Usage: python parse_real_estate_v2.py input.txt -o properties.csv

Changes vs v1 (all verified against 200 real records):
- Description line is no longer skipped; amenities come from the structured
  "Property Facilities / Terrace / Security ..." sections AND the description.
- Captures Sales Type, catastro, tax code, street, unit, zoning, appraisal date,
  site/dwelling value, seller incentive, prior sale, flood map.
- Dates parsed to ISO (invalid ones like 01/00/2025 -> blank + flag).
- Garage text split into garage_cars / driveway_cars.
- Days on market split into number, original asking price and related-party flag.
- Condition/quality parsed separately ("Q4" alone no longer lands in condition_code).
- Price columns follow the site headers: sales_price (Sales Price), appraisal_value
  (Appraisal Value), settled_sale_date (Settled Sale Date); contract_price comes from the
  appraisal's contract section. price_per_sqft and net_price use sales_price because it exists
  on every row; contract/sales differences are flagged, not silently resolved.
- baths_equiv, price_per_sqft, net_price (seller incentive only), dedup_key.
- quality_flags column lists every problem found on the row.
- Buyer, seller and appraiser names/contacts and the free-text description are
  never written to the output.
"""
import argparse
import csv
import re
from datetime import datetime
from pathlib import Path

HEADER = re.compile(r'^ID:\s*(\d+)\t([^\t\n]+)\t([^\t\n]*)\t?([^\t\n]*)')
MONEY = re.compile(r'\$?\s*([\d,]+(?:\.\d+)?)')

FIELDS = {
    'Municipality': 'municipality', 'Street': 'street', 'Address/Unit': 'unit',
    'Latitud': 'latitude', 'Longitud': 'longitude', 'Flood Zone': 'flood_zone',
    'Flood Map': 'flood_map', 'Flood Map Date': 'flood_map_date',
    'GLA(feet)': 'gla_sqft', 'Site(meters)': 'site_sqm', 'Zoning': 'zoning',
    'Rooms': 'rooms', 'Bedrooms': 'bedrooms', 'Bathrooms': 'bathrooms',
    'Full bath': 'full_baths', 'Half bath': 'half_baths',
    'Cons. Type': 'construction_type', 'Conditions': 'condition_raw',
    'Garage': 'garage_raw', 'Actual age': 'actual_age', 'Efective Age': 'effective_age',
    'Stories': 'stories', 'Units': 'units', 'Lender': 'lender',
    'Loan Type': 'loan_type', 'Occupant': 'occupancy',
    'Date of contract': 'contract_date', 'Contract price': 'contract_price',
    'Tax code': 'tax_code', 'Catastro': 'catastro',
    'Appraisal date': 'appraisal_date', 'Opinion of site value': 'site_value',
    'Dwelling sqr./ft. value': 'dwelling_value', 'Days on market': 'dom_raw',
    'HOA': 'hoa_raw', 'Gov. Incentive': 'government_incentive',
    'Dev./Seller Incentive': 'seller_incentive',
    'Prior sale price': 'prior_sale_price', 'Prior sale date': 'prior_sale_date',
    'Source': 'source',
}
# Deliberately NOT parsed (personal data): Buyer, Seller, Appraiser, EPA.
NUMBERS = ['gla_sqft', 'site_sqm', 'latitude', 'longitude', 'rooms', 'bedrooms', 'bathrooms',
           'full_baths', 'half_baths', 'actual_age', 'effective_age', 'stories', 'units']
MONEY_FIELDS = ['contract_price', 'government_incentive', 'seller_incentive',
                'site_value', 'dwelling_value', 'prior_sale_price']
DATE_FIELDS = ['contract_date', 'appraisal_date', 'prior_sale_date', 'flood_map_date']
SECTIONS = {'Extra Parkings', 'Occupancy', 'Property Facilities', 'Sales Type', 'Security',
            'Terrace', 'Water Heater', 'Air Conditioner', 'Complex Facilities', 'Extras'}
AMENITIES = {
    'terrace': r'\bterraces?\b|\bbalcon(?:y|ies)\b', 'fence': r'\bfenc(?:e|es|ed|ing)\b',
    'porch': r'\bporch(?:es)?\b', 'pool': r'\b(?:swimming\s+)?pools?\b',
    'generator': r'\b(?:power\s+)?generators?\b', 'laundry': r'\blaund(?:ry|ries)\b',
    'septic': r'\bseptic\b', 'cistern': r'\bcistern\b', 'solar': r'\bsolar\b',
    'elevator': r'\belevator\b', 'gated': r'\bgat(?:e|ed)\b',
}
WORDNUM = {'one': 1, 'single': 1, 'two': 2, 'double': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6}
PR_LAT, PR_LON = (17.8, 18.6), (-67.5, -65.1)


def money(s):
    m = MONEY.search(s or '')
    return float(m.group(1).replace(',', '')) if m else None


def to_iso(s):
    s = (s or '').strip()
    for fmt in ('%m/%d/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return ''


def norm(s):
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


def parse(text, source_file=''):
    lines = text.splitlines()
    heads = [(i, HEADER.match(l)) for i, l in enumerate(lines) if HEADER.match(l)]
    for n, (idx, m) in enumerate(heads):
        end = heads[n + 1][0] - 2 if n + 1 < len(heads) else len(lines)
        block = lines[idx + 1:end]
        row = {'property_id': m.group(1), 'settled_sale_date': to_iso(m.group(2)),   # site column "Settled Sale Date"
               'sales_price': money(m.group(3)),          # site column "Sales Price" (recorded/settled)
               'appraisal_value': money(m.group(4)),      # site column "Appraisal Value" (blank on registry rows)
               'neighborhood': lines[idx - 2].strip() if idx >= 2 else '',
               'property_type': lines[idx - 1].strip() if idx >= 1 else '',
               'source_file': source_file, 'source_line': idx + 1}
        flags = []
        sections, current, desc = {}, None, ''
        for bi, line in enumerate(block):
            if line.startswith('Colaborar o pedir mas informacion') or line.startswith('Address/Unit:'):
                break
            if line.startswith('Description:'):                 # checked BEFORE the tab test
                desc = line[len('Description:'):].strip()
                current = None
                continue
            if '\t' in line:
                key, value = line.split('\t', 1)
                key, value = key.strip(), value.strip()
                current = None
                if key in FIELDS and key != 'Extras':
                    row[FIELDS[key]] = value
                elif key in SECTIONS:
                    current = key
                continue
            s = line.strip()
            nxt = block[bi + 1].strip() if bi + 1 < len(block) else 'x'
            if s and (s in SECTIONS or (nxt == '' and not s.startswith(('GLA(', 'Site(')))):
                current = s
            elif s and current:
                sections.setdefault(current, []).append(s)

        for k in NUMBERS:
            if k in row:
                try:
                    row[k] = float(row[k].replace(',', ''))
                except ValueError:
                    row[k] = None
        for k in MONEY_FIELDS:
            row[k] = money(row.get(k))
        for k in DATE_FIELDS:
            raw = row.get(k, '')
            row[k] = to_iso(raw)
            if raw and not row[k]:
                flags.append(f'bad_{k}')

        # sections
        st = ' '.join(sections.get('Sales Type', []))
        row['sales_type'] = st
        row['arms_length'] = (1 if re.search(r'arms?\s*length', st, re.I) and not re.search(r'non', st, re.I)
                              else 0 if st else '')
        row['security_features'] = '; '.join(sections.get('Security', []))
        row['complex_facilities'] = '; '.join(sections.get('Complex Facilities', []))
        row['extra_parkings'] = '; '.join(sections.get('Extra Parkings', []))

        # days on market
        dom = row.pop('dom_raw', '')
        d = re.match(r'^\s*(\d+)\b', dom)
        row['days_on_market'] = int(d.group(1)) if d else None
        a = re.search(r'original asking price\s*\$?\s*([\d,]+)', dom, re.I)
        row['original_asking_price'] = float(a.group(1).replace(',', '')) if a else None
        row['related_party_sale'] = int(bool(re.search(r'family|friend|neighbor|relative|related', dom, re.I)))
        row['was_listed'] = 0 if re.search(r'not listed', dom, re.I) else (1 if d else '')
        if (dom and not d and not a and not row['related_party_sale']
                and not re.match(r'unknown|the property was not listed', dom, re.I)):
            flags.append('dom_unrecognized')

        # condition / quality
        raw_c = row.pop('condition_raw', '')
        c, q = re.search(r'\bC\s?([1-6])\b', raw_c), re.search(r'\bQ\s?([1-6])\b', raw_c)
        row['condition_code'] = f'C{c.group(1)}' if c else ''
        row['quality_code'] = f'Q{q.group(1)}' if q else ''
        row['condition_text'] = raw_c if not (c or q) else ''
        if row.get('contract_price') is not None and not (c or q):
            flags.append('no_condition_code')

        # garage: "One Car Carport", "Double Garage", "2 Cars Garage/2 Cars Dwy", "1 Car Cpt/1 Car Dwy", "None"
        g = row.pop('garage_raw', '')
        row['garage_cars'] = row['carport_cars'] = row['driveway_cars'] = (None if not g else 0)
        for part in g.split('/'):
            mm = re.match(r'\s*(\d+|one|two|three|four|five|six|double|single)\b', part, re.I)
            if not mm:
                continue
            w = mm.group(1).lower()
            num = int(w) if w.isdigit() else WORDNUM[w]
            if re.search(r'garage', part, re.I): row['garage_cars'] = num
            elif re.search(r'carport|cpt', part, re.I): row['carport_cars'] = num
            elif re.search(r'driveway|dwy', part, re.I): row['driveway_cars'] = num
            else: flags.append('garage_unrecognized')

        # HOA
        h = row.pop('hoa_raw', '')
        row['hoa_amount'] = money(h)
        row['hoa_frequency'] = 'year' if 'year' in h.lower() else 'month' if 'month' in h.lower() else ''

        # baths
        if row.get('full_baths') is not None:
            row['baths_equiv'] = row['full_baths'] + 0.5 * (row.get('half_baths') or 0)
        else:
            row['baths_equiv'] = row.get('bathrooms')

        # amenities: structured sections + description
        blob = ' '.join([' '.join(v) for k, v in sections.items() if k != 'Sales Type'] + [desc]).lower()
        for name, pat in AMENITIES.items():
            row['has_' + name] = int(bool(re.search(pat, blob)))

        # coordinates
        lat, lon = row.get('latitude'), row.get('longitude')
        if lat is not None and not (PR_LAT[0] <= lat <= PR_LAT[1]):
            flags.append('bad_latitude'); row['latitude'] = None
        if lon is not None and not (PR_LON[0] <= lon <= PR_LON[1]):
            flags.append('bad_longitude'); row['longitude'] = None

        # derived values
        # sales_price = settled/recorded price shown in the list header (present on every row, registry too).
        # contract_price = price in the appraisal's sales contract (missing on registry rows).
        cp, sp, av, gla = row.get('contract_price'), row.get('sales_price'), row.get('appraisal_value'), row.get('gla_sqft')
        row['price_per_sqft'] = round(sp / gla, 2) if sp and gla else None
        # Only seller/developer concessions reduce price. Gov. incentive is buyer assistance.
        row['net_price'] = sp - (row.get('seller_incentive') or 0) if sp else None
        row['contract_minus_sales_price'] = round(cp - sp, 2) if cp is not None and sp is not None else None
        row['contract_matches_sales_price'] = (int(abs(cp - sp) < 1) if cp is not None and sp is not None else '')
        row['sales_to_appraisal_ratio'] = round(sp / av, 3) if sp and av else None

        # checks
        rd, cd = row['settled_sale_date'], row['contract_date']
        if rd and cd:
            gap = (datetime.fromisoformat(rd) - datetime.fromisoformat(cd)).days
            if gap < 0: flags.append('contract_after_settled_date')
            elif gap > 365: flags.append('contract_over_1yr_before_settled')
        if 'karibe' in desc.lower(): flags.append('registry_derived_data')
        if sp is not None and not row['sales_type']: flags.append('no_sales_type')
        if not gla: flags.append('no_gla')
        if cp is None: flags.append('no_contract_price')
        if row.get('source', '').lower().startswith('registry') or 'registr' in row.get('source', '').lower():
            flags.append('registry_source')
        if row['sales_type'] and row['arms_length'] == 0: flags.append('non_arms_length')
        if row['related_party_sale']: flags.append('related_party')
        if (row.get('tax_code') and row.get('catastro')
                and not re.sub(r'\D', '', row['tax_code']).startswith(re.sub(r'\D', '', row['catastro']))):
            flags.append('tax_catastro_mismatch')
        if sp and gla and not (30 <= sp / gla <= 1500): flags.append('price_per_sqft_outlier')
        if sp is not None and sp < 20000: flags.append('very_low_price')
        if row['contract_matches_sales_price'] == 0:
            flags.append('contract_price_differs_from_sales_price')
            if not (0.5 <= cp / sp <= 2): flags.append('contract_price_suspect')
        if row['sales_to_appraisal_ratio'] and not (0.75 <= row['sales_to_appraisal_ratio'] <= 1.25):
            flags.append('sales_price_far_from_appraisal')
        if '?' in (row['neighborhood'] + row.get('street', '')): flags.append('encoding_loss')
        if row.get('catastro') and row['contract_date']:
            row['dedup_key'] = f"{row['catastro']}|{row['contract_date']}"
        elif row.get('street') and row['contract_date']:
            row['dedup_key'] = f"{norm(row['street'])}|{norm(row.get('unit'))}|{row['contract_date']}"
        else:   # registry rows: no catastro or contract date
            row['dedup_key'] = (f"{norm(row['neighborhood'])}|{norm(row.get('unit'))}|{row.get('site_sqm')}|{row['settled_sale_date']}"
                                if row.get('unit') else '')
        row['quality_flags'] = ';'.join(dict.fromkeys(flags))
        yield row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input', type=Path)
    ap.add_argument('-o', '--output', type=Path, default=Path('properties.csv'))
    args = ap.parse_args()
    rows = list(parse(args.input.read_text(encoding='utf-8-sig'), args.input.name))
    columns = list(dict.fromkeys(k for r in rows for k in r))
    with args.output.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=columns, restval='')
        w.writeheader(); w.writerows(rows)
    print(f'Parsed {len(rows)} records into {args.output}; flagged: {sum(bool(r["quality_flags"]) for r in rows)}')


if __name__ == '__main__':
    main()