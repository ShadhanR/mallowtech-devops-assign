from aws_cdk import (
    Stack,
    aws_ec2,
    aws_elasticloadbalancingv2,
    Duration,
    aws_rds,
    aws_secretsmanager,
    aws_s3,
    aws_ecs,
    aws_autoscaling,
    aws_iam
)
from constructs import Construct

class MallowtechStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        vpc = aws_ec2.Vpc(
            self, "mallowtech-vpc",
            ip_addresses=aws_ec2.IpAddresses.cidr("10.1.0.0/16"),
            availability_zones=["ap-south-1a","ap-south-1b"],
            vpc_name="mallowtech-rorapp-vpc",
            enable_dns_hostnames=False,
            subnet_configuration=[
                aws_ec2.SubnetConfiguration(
                    name="mallowtech-rorapp-public1",
                    subnet_type=aws_ec2.SubnetType.PUBLIC,
                    cidr_mask=20
                    ),
                aws_ec2.SubnetConfiguration(
                    name="mallowtech-rorapp-private1",
                    subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=20
                    )
            ]                            
        )
        
        public_subnets = vpc.public_subnets
        private_subnets = vpc.select_subnets(subnet_group_name="mallowtech-rorapp-private1").subnets

    
        #Application Load Balancer
        alb_sg = aws_ec2.SecurityGroup(
            self,"mallowtech-alb-sg",
            description="Security Group for Application Load Balancer",
            security_group_name="mallowtech-ror-alb-sg",
            vpc=vpc,
        )
        alb_sg.add_ingress_rule(
            peer=aws_ec2.Peer.ipv4(vpc.vpc_cidr_block),
            connection=aws_ec2.Port.all_traffic()
            )

        load_balancer = aws_elasticloadbalancingv2.ApplicationLoadBalancer(
            self,"mallowtech-lb",
            load_balancer_name="mallowtech-ror-loadbalancer",
            vpc=vpc,
            security_group=alb_sg,
            http2_enabled=False,
            vpc_subnets=aws_ec2.SubnetSelection(
                subnets=public_subnets,
                ),
            idle_timeout=Duration.seconds(300)
            )
        
        listener = load_balancer.add_listener(
            id="mallowtech-ror-listener",
            port=80,
            open=False,
            protocol=aws_elasticloadbalancingv2.ApplicationProtocol.HTTP,
            # certificates=[aws_elasticloadbalancingv2.ListenerCertificate.from_arn(RegionalCertificateArn)],
            # ssl_policy=aws_elasticloadbalancingv2.SslPolicy.FORWARD_SECRECY_TLS12_RES_GCM,
            default_action=aws_elasticloadbalancingv2.ListenerAction.fixed_response(
                status_code=200,
                content_type="text/plain",
                message_body="test-success"
                )
            )
        
        target_group = aws_elasticloadbalancingv2.ApplicationTargetGroup(
            self, "mallowtech-ror-target-group",
            target_group_name="mallowtech-ror-target-group",
            vpc=vpc,
            port=80,
            protocol=aws_elasticloadbalancingv2.ApplicationProtocol.HTTP,
            health_check=aws_elasticloadbalancingv2.HealthCheck(
                interval=Duration.seconds(35),
                path="/",
                protocol=aws_elasticloadbalancingv2.Protocol.HTTP,
                timeout=Duration.seconds(30),
                healthy_threshold_count=2,
                unhealthy_threshold_count=5,
                port="traffic-port",
                healthy_http_codes="200",
                ),
            deregistration_delay=Duration.seconds(40),
            target_type=aws_elasticloadbalancingv2.TargetType.INSTANCE
            )
        
        #Postgres RDS
        rds_sg = aws_ec2.SecurityGroup(
            self,"mallowtech-db-sg",
            description="Security Group for database",
            security_group_name="mallowtech-ror-db-sg",
            vpc=vpc,
        )
        rds_sg.add_ingress_rule(
            peer=aws_ec2.Peer.ipv4(vpc.vpc_cidr_block),
            connection=aws_ec2.Port.all_traffic()
            )
        
        rds_subnets = aws_rds.SubnetGroup(
            self,"mallowtech-rds-subnets",
            description="Subnets for Db Instances",
            vpc=vpc,
            vpc_subnets=aws_ec2.SubnetSelection(subnets=vpc.private_subnets)
            )
        
        credentials = aws_secretsmanager.Secret.from_secret_name_v2(
            self,"mallowtech-db-creds",
            "mallowtech-db-creds"
            )
        
        database = aws_rds.DatabaseInstance(
            self, "mallowtech-ror-db",
            engine=aws_rds.DatabaseInstanceEngine.postgres(version=aws_rds.PostgresEngineVersion.VER_13_11),
            vpc=vpc,
            port=5432,
            instance_type=aws_ec2.InstanceType.of(aws_ec2.InstanceClass.T4G, aws_ec2.InstanceSize.MICRO),
            instance_identifier="mallowtech-ror-db",
            credentials=aws_rds.Credentials.from_secret(credentials),
            subnet_group=rds_subnets,
            security_groups=[rds_sg]
        )
        cfn_database = database.node.default_child
        cfn_database.add_override(
            "Properties.EngineVersion", "13.20"
                                )

        #S3 bucket
        bucket = aws_s3.Bucket(
            self, "mallowtech-ror-bucket",
            bucket_name="mallowtech-ror-s3-bucket"    
        )

        #ECS Service
        cluster = aws_ecs.Cluster(
            self, "mallowtech-ror-cluster",
            cluster_name="mallowtech-ror-cluster",
            vpc=vpc
        )

        instance_role = aws_iam.Role(
            self, "MallowtechInstanceRole",
            assumed_by=aws_iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                aws_iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonEC2ContainerServiceforEC2Role")
            ]
        )

        user_data = aws_ec2.UserData.for_linux()
        user_data.add_commands(
            f'echo ECS_CLUSTER={cluster.cluster_name} >> /etc/ecs/ecs.config'
        )


        auto_scaling_group = aws_autoscaling.AutoScalingGroup(
            self, "mallowtech-ror-asg",
            vpc=vpc,
            # instance_type=aws_ec2.InstanceType("t2.micro"),
            # machine_image=aws_ecs.EcsOptimizedImage.amazon_linux2(),
            # Or use Amazon ECS-Optimized Amazon Linux 2 AMI
            # machineImage: EcsOptimizedImage.amazonLinux2(),
            desired_capacity=1,
            min_capacity=1,
            max_capacity=2,
            vpc_subnets=aws_ec2.SubnetSelection(subnets=vpc.private_subnets),
            # require_imdsv2=True
            launch_template=aws_ec2.LaunchTemplate(
                self, "mallowtech-lt",
                machine_image=aws_ecs.EcsOptimizedImage.amazon_linux2(),
                instance_type=aws_ec2.InstanceType("t2.micro"),
                role=instance_role,
                security_group=alb_sg,
                user_data=user_data
            )
        )

        capacity_provider = aws_ecs.AsgCapacityProvider(
            self, "mallowtech-capacity-provider",
            auto_scaling_group=auto_scaling_group
        )

        cluster.add_asg_capacity_provider(capacity_provider)

        # task_definition=aws_ecs.TaskDefinition(
        #     self,"mallowtech-ror-task-definition",
        #     family="mallowtech-ror",
        #     network_mode=aws_ecs.NetworkMode.BRIDGE,
        #     compatibility=aws_ecs.Compatibility.EC2,
        #     memory_mib="512",
        #     task_role=task_role,
        #     execution_role=execution_role,
        #     )
