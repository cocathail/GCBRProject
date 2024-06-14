import asyncio
import aiohttp
from tenacity import retry, wait_exponential, stop_after_attempt
import os
from datetime import datetime, timedelta
import matplotlib.pyplot as plt

# Function to read PMIDs from the file
def read_pmids(file_path):
    with open(file_path, 'r') as file:
        pmids = [line.strip() for line in file.readlines()]
    return pmids

# Function to fetch annotations for a given PMID with retries
@retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(5))
async def fetch_annotations(session, pmid):
    url = f"https://www.ebi.ac.uk/europepmc/annotations_api/annotationsByArticleIds"
    params = {
        'articleIds': f'MED:{pmid}',
        'type': 'Accession Numbers',
        'subType': 'bioproject',
        'format': 'JSON'
    }
    headers = {
        'Accept': 'application/json'
    }

    async with session.get(url, headers=headers, params=params) as response:
        if response.status == 200:
            return await response.json()
        else:
            print(f"Error fetching annotations for PMID {pmid}: {response.status}")
            return None

# Function to extract 'name' values from the annotations
def extract_names(annotations):
    names = []
    for annotation in annotations:
        for ann in annotation.get('annotations', []):
            names.extend([tag['name'] for tag in ann.get('tags', [])])
    return names

# Function to write the PMIDs and their corresponding names to a file
def write_results(file_path, results):
    with open(file_path, 'w') as file:
        for pmid, names in results.items():
            names_str = ', '.join(names)
            file.write(f"{pmid}: {names_str}\n")

# Function to check if the file was modified within the last 7 days
def is_recent_file(file_path, days=7):
    if not os.path.exists(file_path):
        return False
    file_mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
    return datetime.now() - file_mod_time < timedelta(days=days)

# Function to count unique names in the results file
def count_unique_names(input_file):
    unique_names = set()
    with open(input_file, 'r') as file:
        for line in file:
            if ': ' in line:
                _, names_str = line.split(': ')
                names = [name.strip() for name in names_str.split(',')]
                unique_names.update(names)
    return len(unique_names)

# Function to write the count of unique names to a file
def write_unique_names_count(file_path, count):
    with open(file_path, 'w') as file:
        file.write(f"Number of unique names: {count}\n")

# Function to fetch citation count for a given PMID with retries
@retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(5))
async def fetch_citation_count(session, pmid):
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/MED/{pmid}/citations"
    params = {
        'page': 1,
        'pageSize': 25,
        'format': 'xml'
    }
    headers = {
        'Accept': 'application/xml'
    }

    async with session.get(url, headers=headers, params=params) as response:
        if response.status == 200:
            text = await response.text()
            start = text.find('<hitCount>') + len('<hitCount>')
            end = text.find('</hitCount>')
            hit_count = int(text[start:end])
            return hit_count
        else:
            print(f"Error fetching citation count for PMID {pmid}: {response.status}")
            return None

# Function to write the citation counts to a file
def write_citation_counts(file_path, citation_counts):
    with open(file_path, 'w') as file:
        for pmid, count in citation_counts.items():
            file.write(f"{pmid}: {count}\n")

# Function to map citation counts to unique names and write to a file
def write_names_with_citation_counts(names_file, citation_counts_file, output_file):
    # Read the unique names from the names file
    pmid_to_names = {}
    with open(names_file, 'r') as file:
        for line in file:
            try:
                pmid, names_str = line.strip().split(': ')
                names = [name.strip() for name in names_str.split(',')]
                pmid_to_names[pmid] = names
            except ValueError:
                print(f"Skipping line due to format issue in names file: {line}")

    # Read the citation counts from the citation counts file
    pmid_to_citation_count = {}
    with open(citation_counts_file, 'r') as file:
        for line in file:
            try:
                pmid, count = line.strip().split(': ')
                pmid_to_citation_count[pmid] = int(count)
            except ValueError:
                print(f"Skipping line due to format issue in citation counts file: {line}")

    # Map the citation counts to the unique names
    names_to_citation_counts = {}
    for pmid, names in pmid_to_names.items():
        if pmid in pmid_to_citation_count:
            count = pmid_to_citation_count[pmid]
            for name in names:
                if name not in names_to_citation_counts:
                    names_to_citation_counts[name] = 0
                names_to_citation_counts[name] += count

    # Write the names and their corresponding citation counts to the output file
    with open(output_file, 'w') as file:
        for name, count in names_to_citation_counts.items():
            file.write(f"{name}: {count}\n")

# Function to create a plot from the names with citation counts file
def create_plot(file_path):
    names = []
    counts = []
    with open(file_path, 'r') as file:
        for line in file:
            name, count = line.strip().split(': ')
            names.append(name)
            counts.append(int(count))

    plt.figure(figsize=(10, 8))
    plt.barh(names, counts, color='skyblue')
    plt.xlabel('Citation Count')
    plt.ylabel('Names')
    plt.title('Citation Counts by Names')
    plt.tight_layout()
    plt.savefig('names_with_citation_counts_plot.png')
    plt.show()

# Main script
async def main():
    input_file = 'pmids.txt'
    output_file = 'pmids_with_names.txt'
    unique_names_count_file = 'unique_names_count.txt'
    citation_counts_file = 'pmid_citation_counts.txt'
    names_with_citation_counts_file = 'names_with_citation_counts.txt'

    # Read PMIDs from the file
    pmids = read_pmids(input_file)
    print(f"PMIDs read: {pmids}")

    # Check if the output files are recent
    results_recent = is_recent_file(output_file)
    citation_counts_recent = is_recent_file(citation_counts_file)

    if not results_recent:
        print(f"{output_file} is not recent. Processing...")
        # Dictionary to store the results
        results = {}

        async with aiohttp.ClientSession() as session:
            tasks = [fetch_annotations(session, pmid) for pmid in pmids]
            annotations_list = await asyncio.gather(*tasks)

        for pmid, annotations in zip(pmids, annotations_list):
            if annotations:
                names = extract_names(annotations)
                results[pmid] = names

        # Write the results to a file
        write_results(output_file, results)
        print(f"Results written to {output_file}")

        # Count unique names and write to another file
        unique_names_count = count_unique_names(output_file)
        write_unique_names_count(unique_names_count_file, unique_names_count)
        print(f"Unique names count written to {unique_names_count_file}")
    else:
        print(f"{output_file} is recent. Skipping processing.")

    if not citation_counts_recent:
        print(f"{citation_counts_file} is not recent. Processing...")
        # Fetch citation counts for each PMID and write to a file
        citation_counts = {}
        async with aiohttp.ClientSession() as session:
            tasks = [fetch_citation_count(session, pmid) for pmid in pmids]
            citation_counts_list = await asyncio.gather(*tasks)

        for pmid, count in zip(pmids, citation_counts_list):
            if count is not None:
                citation_counts[pmid] = count

        write_citation_counts(citation_counts_file, citation_counts)
        print(f"Citation counts written to {citation_counts_file}")
    else:
        print(f"{citation_counts_file} is recent. Skipping processing.")

    # Always update the names with citation counts
    print(f"Updating {names_with_citation_counts_file}...")
    # Map citation counts to unique names and write to a new output file
    write_names_with_citation_counts(output_file, citation_counts_file, names_with_citation_counts_file)
    print(f"Names with citation counts written to {names_with_citation_counts_file}")

    # Create a plot from the names with citation counts file
    create_plot(names_with_citation_counts_file)
    print(f"Plot created from {names_with_citation_counts_file}")

# Run the main script
if __name__ == '__main__':
    asyncio.run(main())
