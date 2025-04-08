import aws_cdk as core
import aws_cdk.assertions as assertions

from mallowtech.mallowtech_stack import MallowtechStack

# example tests. To run these tests, uncomment this file along with the example
# resource in mallowtech/mallowtech_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = MallowtechStack(app, "mallowtech")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
