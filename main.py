import asyncio
import aiohttp
from tenacity import retry, wait_exponential, stop_after_attempt, RetryError
import os
import json
from datetime import datetime, timedelta
import matplotlib.pyplot as plt

# Function to read the configuration file
def read_config(config_file):
    with open(config_file, 'r') as file:
        config = json.load(file)
    return config

# Function to read PMIDs from the file
def read_pmids(file_path):
    with open(file_path, 'r') as file:
        pmids = [line.strip() for line in file.readlines()]
    return pmids

# Function to fetch annotations for a given PMID with retries
@retry(wait=wait_exponential(multiplier=1, min=4, max=60), stop=stop_after_attempt(5))
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

    async with session.get(url, headers=headers, params=params, timeout=60) as response:
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

# Function to fetch citation count for a given PMID with retries
@retry(wait=wait_exponential(multiplier=1, min=4, max=60), stop=stop_after_attempt(5))
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

    async with session.get(url, headers=headers, params=params, timeout=60) as response:
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

    # Sort by counts
    sorted_data = sorted(zip(names, counts), key=lambda x: x[1], reverse=True)
    top_100_data = sorted_data[:100]
    plot_names, plot_counts = zip(*top_100_data)

    # Write names being plotted to a new file
    with open('citation_top_100_names.txt', 'w') as file:
        for name in plot_names:
            file.write(f"{name}\n")

    plt.figure(figsize=(15, 10))
    plt.bar(plot_names, plot_counts, color='skyblue')
    plt.xticks(rotation=90)
    plt.ylabel('Citation Count')
    plt.xlabel('Names')
    plt.title('Top 100 Citation Counts by Names')
    plt.tight_layout()
    plt.savefig('names_with_citation_counts_plot.png')
    plt.show()

# Main script
async def main():
    config_file = 'config.json'
    config = read_config(config_file)
    fetch_data = config.get('fetch_data', True)
    plot_data = config.get('plot_data', True)

    input_file = 'pmids.txt'
    output_file = 'pmids_with_names.txt'
    unique_names_count_file = 'unique_names_count.txt'
    citation_counts_file = 'pmid_citation_counts.txt'
    names_with_citation_counts_file = 'names_with_citation_counts.txt'

    # Read PMIDs from the file
    pmids = read_pmids(input_file)
    print(f"PMIDs read: {pmids}")

    if fetch_data:
        print("Fetching new data...")

        # Fetch and write PMIDs with names
        results = {}
        try:
            async with aiohttp.ClientSession() as session:
                tasks = [fetch_annotations(session, pmid) for pmid in pmids]
                annotations_list = await asyncio.gather(*tasks)
            for pmid, annotations in zip(pmids, annotations_list):
                if annotations:
                    names = extract_names(annotations)
                    results[pmid] = names
            write_results(output_file, results)
            print(f"Results written to {output_file}")
        except RetryError as e:
            print(f"Failed to fetch annotations after retries: {e}")

        # Fetch and write citation counts
        citation_counts = {}
        try:
            async with aiohttp.ClientSession() as session:
                tasks = [fetch_citation_count(session, pmid) for pmid in pmids]
                citation_counts_list = await asyncio.gather(*tasks)
            for pmid, count in zip(pmids, citation_counts_list):
                if count is not None:
                    citation_counts[pmid] = count
            write_citation_counts(citation_counts_file, citation_counts)
            print(f"Citation counts written to {citation_counts_file}")
        except RetryError as e:
            print(f"Failed to fetch citation counts after retries: {e}")
    else:
        print("Using existing data...")

    # Always update the names with citation counts
    print(f"Updating {names_with_citation_counts_file}...")
    write_names_with_citation_counts(output_file, citation_counts_file, names_with_citation_counts_file)
    print(f"Names with citation counts written to {names_with_citation_counts_file}")

    # Create a plot if specified in the config
    if plot_data:
        create_plot(names_with_citation_counts_file)
        print(f"Plot created from {names_with_citation_counts_file}")

# Run the main script
if __name__ == '__main__':
    asyncio.run(main())
