# container-image-pipeline-metrics

Uses Github API to pull in metrics about container image pipeline usage (CircleCI, Serverless framework). The Lambda (rv-anvil-prod) updates the values to Postgres db everyday which is then pulled by Quicksight for various types of dashboards. This will give us more visibility into the usage of these images and help us increase adoption of the images.
