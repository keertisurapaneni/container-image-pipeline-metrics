from github import Github  # Pygithub
from github import RateLimitExceededException
from prettytable import PrettyTable
import regex as regex
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

# Variables
image_lang_list = os.environ['image_lang_list']


def search_github(keywords, run_function, org_list):
    # https://python.gotrained.com/search-github-api/
    rows = 0
    rate_limit = g.get_rate_limit()
    rate = rate_limit.search
    if rate.remaining == 0:
        logger.warning(f'You have 0/{rate.limit} API calls remaining. Reset time: {rate.reset}')
        return
    else:
        logger.info(f'You have {rate.remaining}/{rate.limit} API calls remaining')

    logger.info(keywords)
    table.field_names = ["Date", "Organization", "Repository", "File", "Registry", "Image", "Image Lang", "Version",
                         "Repo URL", "Pipeline Image", "Contributors"]

    orgs = list(org_list.replace(' ','').split(","))
    print(f"Organizations: {orgs}")
    image_langs = list(image_lang_list.replace(' ','').split(","))
    print(f"Image lang list: {image_langs}")

    for org in orgs:
        totalFiles = []
        query = f'"{keywords}" org:{org} filename:Dockerfile'
        result = g.search_code(query, order='desc')
        # https://github.com/PyGithub/PyGithub/issues/1309
        result.get_page(0)
        print(f'Found {result.totalCount} unfiltered Dockerfiles in {org} organization')

        if "non_pipeline_metrics_rv_" in run_function:
            offset = int(run_function.strip("non_pipeline_metrics_rv_"))
            min = (offset - 1) * 15
            max = min + 15
        else:
            min = 0
            max = int(math.ceil(result.totalCount / 30))

        print(f"Parsing info from results in pages {min}-{max}")
        for i in range(min, max): # 30 results per page, 15 pages: 15 x 30 = 450 results
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
        for file in totalFiles: # outer loop
            # https://pygithub.readthedocs.io/en/latest/github_objects/Repository.html#github.Repository.Repository
            if file.repository.archived is False:
                date = time.strftime('%m-%d-%Y')
                source = "N/A"
                filename = file.path
                try:
                    # The search results files that no longer exist, but repository.get_contents will throw 404: not found error, to fix this we have to ignore such files and move to the next item in the loop
                    # For ex: Code was trying to look into the contents of Dockerfile (which doesn't exist) in https://github.com/RedVentures/can-feed-api
                    # 404 {"message": "Not Found", "documentation_url": "https://docs.github.com/rest/reference/repos#get-repository-content"}
                    file_content = file.repository.get_contents(filename)
                except Exception:
                    continue
                url = file.repository.html_url
                repo = file.repository.name
                organization = file.repository.organization.name
                contributors = file.repository.get_contributors()
                contri_list = []
                exclude_list = ['None', 'rv-container-pipeline', 'bot']
                for t in contributors: # inner loop
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
                pattern = r'\b({})\b'.format('|'.join(map(regex.escape, image_langs)))
                # pattern = \b(alpine|dotnet|golang|java|jdk|jre|node|php|python)\b
                # To get unique images in the Dockerfile
                images = re.findall(rf"(^FROM )(.*{pattern}.*)(:)([^\s]+)", content, re.MULTILINE)  # List of lists in a Dockerfile is the output
                images = list(set(images))  # To get unique images in the Dockerfile
                for image in images:
                    combined = '\t'.join(image)  # combine the strings in the list to a single string for a faster check
                    if repo != 'container-image-pipeline':
                        if 'redventures-container-pipeline-docker.jfrog.io' not in combined and '089022728777.dkr.ecr.us-east-1.amazonaws.com' not in combined and 'gcr.io/rv-base-images' not in combined:
                            pipeline_image = "No"
                            if ('java' or 'jdk' or 'jre') in image[1]:
                                image_lang = "java"
                            elif ('alpine' and 'php') in image[1]:
                                image_lang = "php"
                            else:
                                image_lang = image[2]
                            version = image[4]  # selecting 4th group
                            image = image[1]  # selecting first group
                            rows += 1
                            table.add_row([date, organization, repo, filename, source, image, image_lang, version, url,
                                           pipeline_image, contributors])
                        else:
                            break
                            # pipeline_image = "Yes"
                            # if "jfrog.io" in combined:
                            #     source = "Artifactory"
                            # elif "dkr.ecr" in combined:
                            #     source = "ECR"
                            # elif "gcr.io" in (keyword):
                            #     source = "GCR"
                            # else:
                            #     source = "N/A"
                            # version = image[4]  # selecting 4th group
                            # image = image[1].split('/')  # selecting first group
                            # image = image[1]
                            # image_lang = image.split('-')[1]
                            # # if "rv-dotnet" in image:
                            # #     image_version = image.split('-')[3]
                            # # else:
                            # #     image_version = image.split('-')[2]
                            # rows += 1
                            # table.add_row([date, organization, repo, filename, source, image, image_lang, version, url,
                            #                pipeline_image])
                    else:
                        break

    input_string = table.get_string(sort_key=operator.itemgetter(1, 2), sortby="Organization")
    print(input_string)
    logger.info(f'No. of rows in pretty table: {rows}')

    # Convert pretty table to csv: https://stackoverflow.com/questions/32128226/convert-python-pretty-table-to-csv-using-shell-or-batch-command-line
    result = [tuple(filter(None, map(str.strip, splitline))) for line in input_string.splitlines() for splitline in
              [line.split("|")] if len(splitline) > 1]
    with open('/tmp/output.csv', 'w') as outcsv:
        writer = csv.writer(outcsv)
        writer.writerows(result)


# if __name__ == '__main__':
#     keywords = "FROM "
#     search_github(keywords)