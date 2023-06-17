from github import Github  # Pygithub
from github import RateLimitExceededException
from prettytable import PrettyTable
import operator
import re
import logging
import calendar
import time
import math
import csv
import boto3
import os

# Logging https://dev.to/aws-builders/why-you-should-never-ever-print-in-a-lambda-function-3i37
logger = logging.getLogger()
logging.basicConfig(level=logging.INFO)  # To see output in local console
logger.setLevel(logging.INFO)  # To see output in Lambda

# Initialize boto3 client
ssm = boto3.client('ssm')
# Github token
access_token = ssm.get_parameter(Name=os.environ['github_token'], WithDecryption=True)
# login with access token
g = Github(access_token['Parameter']['Value'])

table = PrettyTable()


# https://python.gotrained.com/search-github-api/

def search_github(keywords):
    rows = 0
    rate_limit = g.get_rate_limit()
    rate = rate_limit.search

    if rate.remaining == 0:
        logger.warning(f'You have 0/{rate.limit} API calls remaining. Reset time: {rate.reset}')
        return
    else:
        logger.info(f'You have {rate.remaining}/{rate.limit} API calls remaining')

    logger.info(keywords)
    table.field_names = ["Date", "Organization", "Repository Name", "File Name", "Registry", "Image", "Image Lang", "Version", "Repo URL", "Pipeline Image", "Contributors"]

    keywords = [keyword.strip() for keyword in keywords.split(',')]
    for keyword in keywords:
        totalFiles = []
        registry = keyword.replace(' ', '-')
        query = f'"{keyword}" filename:Dockerfile'
        result = g.search_code(query, order='desc')
        result.get_page(0)
        print(f'Found {result.totalCount} Dockerfiles containing {registry} keyword')

        # https://www.thepythoncode.com/article/using-github-api-in-python
        # https://www.techgeekbuzz.com/how-to-use-github-api-in-python/

        if result.totalCount > 1000:
            max = 20  # 30 results per page, 20 pages: 30x20 = 600 files
            print(f"Limiting results to 600")
        else:
            max = int(math.ceil(result.totalCount / 30))

        # Source/Registry
        if "jfrog.io" in (keyword):
            source = "Artifactory"
        elif "dkr.ecr" in (keyword):
            source = "ECR"
        elif "gcr.io" in (keyword):
            source = "GCR"
        else:
            source = "N/A"

        for i in range(0, max):
            try:
                files = result.get_page(i)
            except StopIteration:
                break
            except RateLimitExceededException:
                search_rate_limit = g.get_rate_limit().search
                logger.warning(f'{search_rate_limit.remaining} API calls remaining')
                reset_timestamp = calendar.timegm(search_rate_limit.reset.timetuple())
                # add 10 seconds to be sure the rate limit has been reset
                sleep_time = reset_timestamp - calendar.timegm(time.gmtime()) + 10
                time.sleep(sleep_time)
                files = result.get_page(i)

            for file in files:
                totalFiles.append(file)

        # print(f"Looking into all {len(totalFiles)} files")
        for file in totalFiles:
            if file.repository.archived is False:
                registry = keyword.replace(' ', '-')
                # https://pygithub.readthedocs.io/en/latest/github_objects/Repository.html#github.Repository.Repository
                filename = file.path
                try:
                    # The search results files that no longer exist, but repository.get_contents will throw 404: not found error, to fix this we have to ignore such files and move to the next item in the loop
                    file_content = file.repository.get_contents(filename)
                except Exception:
                    continue
                repo = file.repository.name
                organization = file.repository.organization.name
                url = file.repository.html_url
                contributors = file.repository.get_contributors()
                contri_list = []
                exclude_list = ['None', 'rv-container-pipeline', 'bot']
                for t in contributors:
                    if not any(x in t.login for x in exclude_list):
                        contri_list.append(str(t.login))
                        if len(contri_list) == 3:
                            break
                if not contri_list:
                    contri_list.append('None')
                    # print(f"Contributor is null for this file..ignoring it: {repo}/{filename}")
                    # continue  # go to next element          
                contributors = ';'.join(contri_list)
                content = file_content.decoded_content.decode()
                images = re.findall(rf"(^FROM.*)({registry}.*)(:)([^\s]+)", content, re.MULTILINE)
                images = list(set(images))  # To get unique images in the Dockerfile
                # print(images)
                for image in images:
                    # print(image)
                    if repo != "container-image-pipeline":
                        pipeline_image = "Yes"
                        version = image[3].split(' ')  # selecting third group
                        version = version[0]
                        image = image[1].split('/')  # selecting first group
                        image = image[1]
                        image_lang = image.split('-')[1]
                        date = time.strftime('%m-%d-%Y')
                        rows += 1
                        table.add_row([date, organization, repo, filename, source, image, image_lang, version, url, pipeline_image, contributors])
                    else:
                        break

    input_string = table.get_string(sort_key=operator.itemgetter(1, 2), sortby="Organization")
    print(input_string)
    logger.info(f'No. of row(s) in pretty table: {rows}')

    # Convert pretty table to csv: https://stackoverflow.com/questions/32128226/convert-python-pretty-table-to-csv-using-shell-or-batch-command-line
    result = [tuple(filter(None, map(str.strip, splitline))) for line in input_string.splitlines() for splitline in
              [line.split("|")] if len(splitline) > 1]
    with open('/tmp/output.csv', 'w') as outcsv:
        writer = csv.writer(outcsv)
        writer.writerows(result)


# if __name__ == '__main__':
#     keywords = "089022728777.dkr.ecr.us east 1.amazonaws.com, redventures container pipeline docker.jfrog.io"
#     search_github(keywords)
