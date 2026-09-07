export type Store = {
    id: number;
    name: string;
    floor: string;
    floorThai: string;
    hours: string;
    logo: string;
    color: string;
    address: string;
    category: string;
    logoSrc: string;
};

export function parseStoreCsv(raw: string): Store[] {
    const lines = raw.trim().split(/\r?\n/);
    const headerLine = lines.shift();
    if (!headerLine) return [];

    const headers = splitCsvLine(headerLine);

    return lines
        .filter((line) => line.length)
        .map((line) => {
            const values = splitCsvLine(line);
            const record: Record<string, string> = {};
            headers.forEach((header, index) => {
                record[header] = values[index] ?? '';
            });
            return {
                id: Number(record.id),
                name: record.name,
                floor: record.floor,
                floorThai: record.floorThai,
                hours: record.hours?.replaceAll('"', '') ?? '',
                logo: record.logo,
                color: record.color,
                address: record.address,
                category: record.category,
                logoSrc: record.logoSrc
            };
        });
}

function splitCsvLine(line: string): string[] {
    const result: string[] = [];
    let current = '';
    let inQuotes = false;

    for (let i = 0; i < line.length; i += 1) {
        const char = line[i];
        if (char === '"') {
            inQuotes = !inQuotes;
            continue;
        }

        if (char === ',' && !inQuotes) {
            result.push(current.trim());
            current = '';
        } else {
            current += char;
        }
    }

    result.push(current.trim());
    return result.map((value) => value.replace(/^"(.*)"$/, '$1'));
}
