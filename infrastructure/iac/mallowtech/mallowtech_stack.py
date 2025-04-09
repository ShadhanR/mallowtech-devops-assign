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
    aws_iam,
    aws_logs,
    aws_ecr,
    aws_elasticloadbalancingv2,
    RemovalPolicy
)
from constructs import Construct

class MallowtechStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        #Network components
        #VPC
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

        #Load Balancer components
        #Security group
        alb_sg = aws_ec2.SecurityGroup(
            self,"mallowtech-alb-sg",
            description="Security Group for Application Load Balancer",
            security_group_name="mallowtech-ror-alb-sg",
            vpc=vpc,
        )
        alb_sg.add_ingress_rule(
            peer=aws_ec2.Peer.any_ipv4(),
            connection=aws_ec2.Port.all_traffic()
            )

        #ALB
        load_balancer = aws_elasticloadbalancingv2.ApplicationLoadBalancer(
            self,"mallowtech-lb",
            load_balancer_name="mallowtech-ror-loadbalancer-if",
            vpc=vpc,
            security_group=alb_sg,
            http2_enabled=False,
            vpc_subnets=aws_ec2.SubnetSelection(
                subnets=public_subnets,
                ),
            idle_timeout=Duration.seconds(300),
            internet_facing=True
            )
        
        #Target group
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
        
        listener = load_balancer.add_listener(
            id="mallowtech-ror-listener",
            port=80,
            open=False,
            protocol=aws_elasticloadbalancingv2.ApplicationProtocol.HTTP,
            default_action=aws_elasticloadbalancingv2.ListenerAction.forward(
                target_groups=[target_group]
                )
            )
        
        # aws_elasticloadbalancingv2.ApplicationListenerRule(
        #     self, "mallowtech-ror-lr",
        #     listener=listener,
        #     priority=1,
        #     conditions=[aws_elasticloadbalancingv2.ListenerCondition.path_patterns(['/'])],
        #     action=aws_elasticloadbalancingv2.ListenerAction.forward(target_groups=[target_group])
        #     )
        
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

        #ECS Cluster
        cluster = aws_ecs.Cluster(
            self, "mallowtech-ror-cluster",
            cluster_name="mallowtech-ror-cluster",
            vpc=vpc
        )

        #ECS cluster indtance role
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

        #ECS Security Group
        ecs_sg = aws_ec2.SecurityGroup(
            self,"mallowtech-ecs-sg",
            description="Security Group for Application ECS",
            security_group_name="mallowtech-ror-ecs-sg",
            vpc=vpc,
        )
        ecs_sg.add_ingress_rule(
            peer=aws_ec2.Peer.ipv4(vpc.vpc_cidr_block),
            connection=aws_ec2.Port.all_traffic()
            )

        #ASG
        auto_scaling_group = aws_autoscaling.AutoScalingGroup(
            self, "mallowtech-ror-asg",
            vpc=vpc,
            desired_capacity=1,
            min_capacity=1,
            max_capacity=2,
            vpc_subnets=aws_ec2.SubnetSelection(subnets=vpc.private_subnets),
            launch_template=aws_ec2.LaunchTemplate(
                self, "mallowtech-lt",
                machine_image=aws_ecs.EcsOptimizedImage.amazon_linux2(),
                instance_type=aws_ec2.InstanceType("t2.micro"),
                role=instance_role,
                security_group=ecs_sg,
                user_data=user_data
            )
        )

        capacity_provider = aws_ecs.AsgCapacityProvider(
            self, "mallowtech-capacity-provider",
            auto_scaling_group=auto_scaling_group
        )

        cluster.add_asg_capacity_provider(capacity_provider)

        #Service Execution Role
        execution_role = aws_iam.Role(
            self,'mallowtech-ror-exec-role',
            role_name='mallowtech-ror-exec-role',
            assumed_by=aws_iam.ServicePrincipal('ecs-tasks.amazonaws.com')
                    )
        execution_role.add_managed_policy(
            aws_iam.ManagedPolicy.from_managed_policy_arn(
                self,"mallowtech-ror-exec-policy",
                managed_policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
                )
            )

        #Service Task Role
        task_role = aws_iam.Role(
            self,'mallowtech-ror-task-role',
            role_name='mallowtech-ror-task-role',
            assumed_by=aws_iam.ServicePrincipal('ecs-tasks.amazonaws.com')
                    )
        task_role.add_managed_policy(
            aws_iam.ManagedPolicy.from_managed_policy_arn(
                self,"mallowtech-ror-task-s3-policy",
                managed_policy_arn="arn:aws:iam::aws:policy/AmazonS3FullAccess"
                    )
            )
        task_role.add_managed_policy(
            aws_iam.ManagedPolicy.from_managed_policy_arn(
                self,"mallowtech-ror-task-cw-policy",
                managed_policy_arn="arn:aws:iam::aws:policy/CloudWatchFullAccess"
                    )
            )
        task_role.add_managed_policy(
            aws_iam.ManagedPolicy.from_managed_policy_arn(
                self,"mallowtech-ror-task-cwv2-policy",
                managed_policy_arn="arn:aws:iam::aws:policy/CloudWatchFullAccessV2"
                    )
            )
        
        #Log group for service
        log_group = aws_logs.LogGroup(
            self, "mallowtech-ror-log-group",
            log_group_name="/ecs/mallowtech-ror",
            removal_policy=RemovalPolicy.DESTROY
        )

        #Task definition
        task_definition = aws_ecs.TaskDefinition(
            self, "mallowtech-ror-td",
            network_mode=aws_ecs.NetworkMode.BRIDGE,
            memory_mib='768',
            compatibility=aws_ecs.Compatibility.EC2,
            task_role=task_role,
            execution_role=execution_role,
            family='mallowtech-ror-td-family'
        )

        ecr_repository=aws_ecr.Repository.from_repository_arn(
            self,"mallowtech-ror-ecr",
            'arn:aws:ecr:ap-south-1:919113286795:repository/mallowtech-ror'
            )    

        secret = aws_secretsmanager.Secret.from_secret_name_v2(
           self, "Secret",
           secret_name='mallowtech-db-creds'
        )
        
        #App container definition
        rails_container = task_definition.add_container(
            "rails_app",
            container_name="rails_app",
            image=aws_ecs.ContainerImage.from_ecr_repository(
                repository=ecr_repository,
                tag='latest-app'
                ),
            essential=False,
            memory_reservation_mib=256,
            secrets = {
                "RDS_PASSWORD":aws_ecs.Secret.from_secrets_manager(
                    secret=secret,
                    field='password'
                    ),
                "RDS_USERNAME":aws_ecs.Secret.from_secrets_manager(
                    secret=secret,
                    field='username'
                    ),
                },
            environment={
                "RDS_HOSTNAME": database.db_instance_endpoint_address,
                "RDS_PORT": database.db_instance_endpoint_port,
                "S3_REGION_NAME": "ap-south-1",
                "RDS_DB_NAME": 'ror-app',
                "LB_ENDPOINT": load_balancer.load_balancer_dns_name,
                "S3_BUCKET_NAME": bucket.bucket_name
            },
            logging=aws_ecs.LogDriver.aws_logs(
                stream_prefix="rorapp",
                log_group=log_group,
                mode=aws_ecs.AwsLogDriverMode.NON_BLOCKING
            )
        )

        rails_container.add_port_mappings(
            aws_ecs.PortMapping(
                container_port=3000,
                host_port=0,
                protocol=aws_ecs.Protocol.TCP,
            )
        )

        #Nginx container definition
        nginx_container = task_definition.add_container(
            "nginx",
            image=aws_ecs.ContainerImage.from_ecr_repository(
                repository=ecr_repository,
                tag='latest-nginx'
                ),
            container_name="nginx",
            essential=True,
            memory_reservation_mib=256,
            start_timeout=Duration.seconds(120),
            stop_timeout=Duration.seconds(120),
            logging=aws_ecs.LogDriver.aws_logs(
                stream_prefix="nginx",
                log_group=log_group,
                mode=aws_ecs.AwsLogDriverMode.NON_BLOCKING,
            )
        )

        nginx_container.add_port_mappings(
            aws_ecs.PortMapping(
                container_port=80,
                host_port=0,
                protocol=aws_ecs.Protocol.TCP
            )
        )

        nginx_container.add_container_dependencies(
            aws_ecs.ContainerDependency(
                container=rails_container,
                condition=aws_ecs.ContainerDependencyCondition.START
            )
        )

        nginx_container.add_link(container=rails_container,alias='rails_app')

        #ECS service
        ecs_service=aws_ecs.Ec2Service(
            self,"mallowtech-ror-ecs-svc",
            service_name='mallowtech-ror-ecs-svc',
            task_definition=task_definition,
            cluster=cluster,
            desired_count=1
            )
                                                                    
        ecs_service.attach_to_application_target_group(target_group=target_group)
