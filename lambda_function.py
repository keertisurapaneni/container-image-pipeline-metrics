import psycopg2
import logging
import boto3
import os
import pipeline_metrics_all
import non_pipeline_metrics

# Logging https://dev.to/aws-builders/why-you-should-never-ever-print-in-a-lambda-function-3i37
logger = logging.getLogger()
logging.basicConfig(level=logging.INFO)  # To see output in local console
logger.setLevel(logging.INFO)  # To see output in Lambda

# Initialize boto3 client
ssm = boto3.client('ssm')
sns = boto3.client('sns')

# Variables
DBTABLE = os.environ['db_table']
ENDPOINT = os.environ['db_endpoint']
DBNAME = os.environ['db_name']
DBUSER = os.environ['db_user']
PORT = os.environ['db_port']
DBPASS = ssm.get_parameter(Name=os.environ['db_pass'], WithDecryption=True)
SNS_TOPIC = os.environ['sns_topic']

def notify(text):
    try:
        sns.publish(TopicArn=SNS_TOPIC,
            Subject='Container pipeline metrics error',
            Message=text)
    except Exception as e:
        logger.error("Sending notification failed: {}".format(e))
        exit(1)
    logger.info(text)


def main(event, context):
    try:
        conn = psycopg2.connect(host=ENDPOINT, port=PORT, database=DBNAME, user=DBUSER, password=DBPASS['Parameter']['Value'])
        cur = conn.cursor()
    except Exception as e:
        notify("Database connection failed due to {}".format(e))
        exit(1)

    try:
        run_function = event['run_function']
        if run_function == "pipeline_metrics_all":
            function = pipeline_metrics_all.search_github("089022728777.dkr.ecr.us east 1.amazonaws.com, redventures container pipeline docker.jfrog.io")
        elif "non_pipeline_metrics" in run_function:
            org_list = event['org_list']
            function = non_pipeline_metrics.search_github("FROM ", run_function, org_list)
        else:
            notify("Invalid function provided..exiting")
            exit(1)
        function
    except Exception as e:
        notify("Creation of search metrics CSV failed due to {}".format(e))
        exit(1)

    try:
        # Create table if table doesn't exist
        cur.execute(f"CREATE TABLE IF NOT EXISTS {DBTABLE} (Date TIMESTAMP, Organization VARCHAR, Repository VARCHAR, Filename VARCHAR, Registry VARCHAR, Image VARCHAR, ImageLang VARCHAR, Version VARCHAR, RepoURL VARCHAR, PipelineImage VARCHAR, TopContributors VARCHAR, PRIMARY KEY (Date, Organization, Repository, Filename, Registry, Image, Version))")
        cur.execute(f"SELECT COUNT(*) AS num_rows FROM {DBTABLE}")
        query_results = cur.fetchone()
        logger.info(f"Num of rows in db table {DBTABLE}: {query_results[0]}")
        cur.execute(f"SET datestyle TO ISO, MDY")
    except (Exception, psycopg2.DatabaseError) as e:
        notify(f"Unable to find info about db table: {e}")
        exit(1)
    if query_results[0] == 0:
        # If db table is empty, insert data for the first time
        try:
            logger.info("Trying to insert data for the first time...")
            # Here we are going load the csv file and use copy_from() to copy it to db table
            tmp_csv = "/tmp/output.csv"
            with open(tmp_csv, 'r') as f:
                next(f)  # skip the first line
                cur.copy_from(f, DBTABLE, sep=",")
            os.remove(tmp_csv)
        except (Exception, psycopg2.DatabaseError) as e:
            notify(f"First data insertion into db table failed: {e}")
            exit(1)
        cur.execute(f"SELECT COUNT(*) AS num_rows FROM {DBTABLE}")
        query_results = cur.fetchone()
        text = f"First data insertion successfully completed!\n"
        text += f"\nNum of rows inserted into db table {DBTABLE}: {query_results[0]}"
        print(text)
    else:
        # If db table is not empty, load new data records into db table
        try:
            # Clone table structure of destination table to a temp table
            tmp_table = "tmp"
            # cur.execute(f"CREATE TEMPORARY TABLE {tmp_table} (Date TIMESTAMP, Organization VARCHAR, Repository VARCHAR, Filename VARCHAR, Registry VARCHAR, Image VARCHAR, ImageLang VARCHAR, Version VARCHAR, RepoURL VARCHAR, PipelineImage VARCHAR, PRIMARY KEY (Organization, Repository, Filename, Registry, Image, Version))")
            cur.execute(f"CREATE TEMPORARY TABLE {tmp_table} AS (SELECT * FROM {DBTABLE} LIMIT 0)")

            # Copy data into the temp table
            tmp_csv = "/tmp/output.csv"
            with open(tmp_csv, 'r') as f:
                next(f)  # skip the first line
                cur.copy_from(f, tmp_table, sep=",")
            os.remove(tmp_csv)

            # Copy all records found today present in temp table to db table
            cur.execute(f"INSERT INTO {DBTABLE} SELECT tmp.* FROM {tmp_table} EXCEPT SELECT * FROM {DBTABLE} ON CONFLICT DO NOTHING")
            # Drop the temporary table
            cur.execute(f"DROP TABLE {tmp_table}")

            cur.execute(f"SELECT COUNT(*) AS num_rows FROM {DBTABLE}")
            query_results = cur.fetchone()
            print(f"Num of rows in db table {DBTABLE}: {query_results[0]}")
        except (Exception, psycopg2.DatabaseError) as e:
            notify(f"Daily insertion of data failed: {e}")
            exit(1)


    cur.close()
    conn.commit()


if __name__ == '__main__':
    main(event =[], context =[])