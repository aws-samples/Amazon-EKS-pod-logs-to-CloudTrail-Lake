import boto3
import json
import object_wrapper
from datetime import datetime
import uuid
from urllib.parse import urlparse

def lambda_handler(event, context):

    # Initialize client
    cloudtrail = boto3.client('cloudtrail-data')

    ssm = boto3.client('ssm')

    PodNameFilter=ssm.get_parameter(Name='/EKS-CloudTrailLake-PodLog-App/PodNamesParameter', WithDecryption=True)['Parameter']['Value']
    PodNameFilter = PodNameFilter.split(",")
    bucket_url = ssm.get_parameter(Name='/EKS-CloudTrailLake-PodLog-App/EKSS3LogLocationParameter', WithDecryption=True)['Parameter']['Value']
    bucket_name = urlparse(bucket_url,allow_fragments=False).netloc
    channelArn = ssm.get_parameter(Name='/EKS-CloudTrailLake-PodLog-App/CloudTrailLakeChannelArnParameter', WithDecryption=True)['Parameter']['Value']

    # Initialize client
    s3_resource = boto3.resource("s3")
    s3_bucket = s3_resource.Bucket(bucket_name)
    cloudtrail = boto3.client('cloudtrail-data')

    # Loop through all the objects in the S3 bucket folders
    listed_lines = object_wrapper.ObjectWrapper.list(s3_bucket,prefix="pod-logs")
    if isinstance(listed_lines, list): #Check if the object is a list
        for l in listed_lines:
            obj_wrapper = object_wrapper.ObjectWrapper(s3_bucket.Object(l.key))
            for  PodNameFilterValue in PodNameFilter:
                if PodNameFilterValue in l.key:
                    #Get s3 objects with key containing PodNameFilterValue and decode the object
                    txt = obj_wrapper.get();
                    decodedtxt= txt.decode("utf-8")
                    logs = decodedtxt.replace('}\n{','},{') #Convert into JSON Array
                    logs = '[' + logs + ']'#Convert into JSON Array
                    try:
                        logs_json = json.loads(logs)
                        #calculate the length of the JSON object
                        length = len(logs_json)
                        #print("Length of JSON object: " + str(length))
                        #iterate through the JSON object 100 records at a time and publish to CloudTrail
                        for i in range(0, length, 100):
                        #Read values in range i to i+100
                            logs_json_ = logs_json[i:i+100]
                            for log in logs_json_:
                                auditEventsData = []
                                eventTimeStr = log["date"]
                                eventTimeDt = datetime.strptime(eventTimeStr,"%Y-%m-%dT%H:%M:%S.%fZ")
                                eventTimeArg = eventTimeDt.strftime("%Y-%m-%dT%H:%M:%S") + 'Z'
                                hostname = log["kubernetes"]["host"]
                                eventName =  log["stream"]
                                message = log["log"]
                                podname = log["kubernetes"]["namespace_name"]+ "-" + log["kubernetes"]["pod_name"]
                                ACCOUNT_ID = context.invoked_function_arn.split(":")[4]
                                uid = str(uuid.uuid4())
                                #create a JSON object for CloudTrail Lake
                                eventData = {
                                    "version": "0.1",
                                    "userIdentity": {
                                        "type": podname,
                                        "principalId": hostname,
                                        "details": {
                                            "message": message
                                        }
                                    },
                                    "eventSource": hostname,
                                    "eventName": eventName,
                                    "eventTime": eventTimeArg,
                                    "UID": uid,
                                    "recipientAccountId": ACCOUNT_ID,
                                    "additionalEventData": {
                                        "message": log
                                    }
                                }

                                eventDataStr = json.dumps(eventData)

                                auditEventsData.append(
                                    {
                                        "id": uid,
                                        "eventData": eventDataStr
                                    }
                                )

                        response = cloudtrail.put_audit_events(auditEvents=auditEventsData, channelArn=channelArn)

                        print("Published to CloudTrail Lake:" + json.dumps(response))

                    except json.decoder.JSONDecodeError as e:
                        print("Error decoding JSON")
                        print(e)
                        break

            copied_obj = s3_bucket.Object("backup_" + l.key)
            obj_wrapper.copy(copied_obj)
            print(f"Made a copy of object {l.key}, named {copied_obj.key}.")
            obj_wrapper.delete()
            print(f"Deleted object with key {l.key}.")

    return {
        "statusCode": 200,
         "body": json.dumps({
         "message": "Success",
            }),
    }
