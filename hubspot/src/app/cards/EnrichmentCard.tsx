import {
  Alert,
  DescriptionList,
  DescriptionListItem,
  Divider,
  EmptyState,
  Flex,
  Link,
  LoadingSpinner,
  StatusTag,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Text,
  hubspot,
} from '@hubspot/ui-extensions';
import { useRecordPropertiesCurrent } from '@hubspot/ui-extensions/crm';
import type { ReactNode } from 'react';

type Props = Record<string, string | null>;
type Verdict = 'agree' | 'differs' | null;
type TagVariant = 'success' | 'warning' | 'danger' | 'default';

const PROPERTIES = [
  'founded_year',
  'numberofemployees',
  'annualrevenue',
  'industry',
  'city',
  'state',
  'is_public',
  'wikidata_id',
  'wikidata_founded_year',
  'wikidata_employee_count',
  'wikidata_industry',
  'wikidata_match_status',
  'wikidata_match_score',
  'wikidata_match_reasons',
  'wikidata_last_checked',
  'edgar_cik',
  'edgar_ticker',
  'edgar_sic_description',
  'edgar_business_location',
  'edgar_state_of_incorporation',
  'edgar_incorporation_source',
  'edgar_annual_revenue',
  'edgar_revenue_fiscal_year',
  'edgar_match_status',
  'edgar_match_method',
  'edgar_last_checked',
];

const STATUS: Record<string, [string, TagVariant]> = {
  matched: ['Matched', 'success'],
  ambiguous: ['Ambiguous, needs review', 'warning'],
  no_item: ['No Wikidata item', 'default'],
  rejected: ['Only non-organization matches', 'default'],
  name_conflict: ['Name conflict, needs review', 'danger'],
  no_cik: ['No CIK found', 'default'],
  not_found: ['CIK not found', 'default'],
};

const METHOD: Record<string, string> = {
  wikidata_cik: 'CIK from Wikidata',
  sec_name_lookup: 'SEC name lookup, corroborated by state',
};

// Same tolerances as enrichment/compare.py.
const RATIO_TOLERANCE = 1.1;
const YEAR_TOLERANCE = 1;

hubspot.extend<'crm.record.tab'>(() => <EnrichmentCard />);

const EnrichmentCard = () => {
  const {
    properties: p,
    isLoading,
    error,
  } = useRecordPropertiesCurrent({ properties: PROPERTIES });

  if (isLoading) return <LoadingSpinner label="Loading enrichment data" />;
  if (error)
    return (
      <Alert title="Couldn't load properties" variant="danger">
        {error.message}
      </Alert>
    );
  if (!p.wikidata_match_status && !p.edgar_match_status) {
    return (
      <EmptyState title="Not enriched yet" layout="vertical">
        <Text>Run the enrichment script to populate this card.</Text>
      </EmptyState>
    );
  }

  return (
    <Flex direction="column" gap="md">
      <DescriptionList direction="row">
        <DescriptionListItem label="Wikidata">
          <SourceStatus
            status={p.wikidata_match_status}
            checked={p.wikidata_last_checked}
          >
            {p.wikidata_match_score && (
              <Text inline>score {p.wikidata_match_score}</Text>
            )}
            {p.wikidata_id && (
              <Link href={`https://www.wikidata.org/wiki/${p.wikidata_id}`}>
                {p.wikidata_id}
              </Link>
            )}
          </SourceStatus>
        </DescriptionListItem>
        <DescriptionListItem label="SEC EDGAR">
          <SourceStatus
            status={p.edgar_match_status}
            checked={p.edgar_last_checked}
          >
            {p.edgar_match_method && (
              <Text inline>
                {METHOD[p.edgar_match_method] ?? p.edgar_match_method}
              </Text>
            )}
            {p.edgar_cik && (
              <Link
                href={`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${p.edgar_cik}`}
              >
                CIK {p.edgar_cik}
              </Link>
            )}
          </SourceStatus>
        </DescriptionListItem>
      </DescriptionList>

      <Divider />
      <Text format={{ fontWeight: 'bold' }}>Sources compared</Text>
      <Table bordered density="compact">
        <TableHead>
          <TableRow>
            <TableHeader>Field</TableHeader>
            <TableHeader>HubSpot</TableHeader>
            <TableHeader>Wikidata</TableHeader>
            <TableHeader>EDGAR</TableHeader>
            <TableHeader width="min">Agreement</TableHeader>
          </TableRow>
        </TableHead>
        <TableBody>
          {comparisonRows(p).map((row) => (
            <TableRow key={row.field}>
              <TableCell>{row.field}</TableCell>
              <TableCell>{row.hubspot ?? '–'}</TableCell>
              <TableCell>{row.wikidata ?? '–'}</TableCell>
              <TableCell>{row.edgar ?? '–'}</TableCell>
              <TableCell>
                {row.verdict === 'agree' && (
                  <StatusTag variant="success">Agree</StatusTag>
                )}
                {row.verdict === 'differs' && (
                  <StatusTag variant="warning">Differs</StatusTag>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {p.wikidata_match_reasons && (
        <>
          <Divider />
          <Text format={{ fontWeight: 'bold' }}>Why this Wikidata result</Text>
          {p.wikidata_match_reasons.split('\n').map((line) => (
            <Text key={line} variant="microcopy">
              {line}
            </Text>
          ))}
        </>
      )}
    </Flex>
  );
};

const SourceStatus = ({
  status,
  checked,
  children,
}: {
  status: string | null;
  checked: string | null;
  children?: ReactNode;
}) => {
  if (!status) return <Text variant="microcopy">Not checked</Text>;
  const [label, variant] = STATUS[status] ?? [status, 'default'];
  return (
    <Flex direction="column" gap="xs">
      <StatusTag variant={variant}>{label}</StatusTag>
      <Flex gap="sm">{children}</Flex>
      {checked && <Text variant="microcopy">Checked {isoDate(checked)}</Text>}
    </Flex>
  );
};

interface Row {
  field: string;
  hubspot: string | null;
  wikidata: string | null;
  edgar: string | null;
  verdict: Verdict;
}

const comparisonRows = (p: Props): Row[] => {
  const ticker = p.edgar_ticker;
  const edgarPublic =
    p.edgar_match_status === 'matched'
      ? ticker
        ? `Public (${ticker})`
        : 'No ticker'
      : null;
  const hubspotPublic =
    p.is_public === 'true'
      ? 'Public'
      : p.is_public === 'false'
        ? 'Private'
        : null;
  const fiscalYear = p.edgar_revenue_fiscal_year
    ? ` (FY${p.edgar_revenue_fiscal_year})`
    : '';

  return [
    {
      field: 'Founded',
      hubspot: p.founded_year,
      wikidata: p.wikidata_founded_year,
      edgar: null,
      verdict: compare(
        p.founded_year,
        p.wikidata_founded_year,
        (a, b) => Math.abs(a - b) <= YEAR_TOLERANCE,
      ),
    },
    {
      field: 'Employees',
      hubspot: count(p.numberofemployees),
      wikidata: count(p.wikidata_employee_count),
      edgar: null,
      verdict: compare(
        p.numberofemployees,
        p.wikidata_employee_count,
        withinRatio,
      ),
    },
    {
      field: 'Annual revenue',
      hubspot: money(p.annualrevenue),
      wikidata: null,
      edgar: p.edgar_annual_revenue
        ? `${money(p.edgar_annual_revenue)}${fiscalYear}`
        : null,
      verdict: compare(p.annualrevenue, p.edgar_annual_revenue, withinRatio),
    },
    {
      field: 'Public or private',
      hubspot: hubspotPublic,
      wikidata: null,
      edgar: edgarPublic,
      verdict:
        hubspotPublic && edgarPublic
          ? (hubspotPublic === 'Public') === Boolean(ticker)
            ? 'agree'
            : 'differs'
          : null,
    },
    // Locations and industries use different formats and taxonomies; shown without a verdict.
    {
      field: 'Location',
      hubspot: [p.city, p.state].filter(Boolean).join(', ') || null,
      wikidata: null,
      edgar: p.edgar_business_location,
      verdict: null,
    },
    {
      field: 'Incorporated',
      hubspot: null,
      wikidata: null,
      edgar: p.edgar_state_of_incorporation
        ? `${p.edgar_state_of_incorporation} (${p.edgar_incorporation_source ?? 'unknown source'})`
        : null,
      verdict: null,
    },
    {
      field: 'Industry',
      hubspot: p.industry,
      wikidata: p.wikidata_industry,
      edgar: p.edgar_sic_description,
      verdict: null,
    },
  ];
};

const compare = (
  a: string | null,
  b: string | null,
  agrees: (x: number, y: number) => boolean,
): Verdict => {
  const x = Number(a);
  const y = Number(b);
  if (!a || !b || !x || !y) return null;
  return agrees(x, y) ? 'agree' : 'differs';
};

const withinRatio = (a: number, b: number) =>
  Math.max(a, b) / Math.min(a, b) <= RATIO_TOLERANCE;

const count = (value: string | null) =>
  value ? Number(value).toLocaleString('en-US') : null;

const money = (value: string | null) => {
  if (!value) return null;
  const n = Number(value);
  return n >= 1e9 ? `$${(n / 1e9).toFixed(2)}B` : `$${(n / 1e6).toFixed(1)}M`;
};

// HubSpot returns date properties as epoch milliseconds.
const isoDate = (value: string) =>
  /^\d+$/.test(value)
    ? new Date(Number(value)).toISOString().slice(0, 10)
    : value;
