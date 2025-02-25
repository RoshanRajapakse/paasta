import logging
from typing import List
from typing import Mapping
from typing import Optional

import service_configuration_lib

from paasta_tools.kubernetes_tools import sanitise_kubernetes_name
from paasta_tools.kubernetes_tools import sanitised_cr_name
from paasta_tools.long_running_service_tools import LongRunningServiceConfig
from paasta_tools.long_running_service_tools import LongRunningServiceConfigDict
from paasta_tools.utils import BranchDictV2
from paasta_tools.utils import compose_job_id
from paasta_tools.utils import decompose_job_id
from paasta_tools.utils import deep_merge_dictionaries
from paasta_tools.utils import DEFAULT_SOA_DIR
from paasta_tools.utils import InvalidJobNameError
from paasta_tools.utils import load_service_instance_config
from paasta_tools.utils import load_v2_deployments_json

KUBERNETES_NAMESPACE = "paasta-vitess"

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


class VitessDeploymentConfigDict(LongRunningServiceConfigDict, total=False):
    replicas: int


class VitessDeploymentConfig(LongRunningServiceConfig):
    config_dict: VitessDeploymentConfigDict

    config_filename_prefix = "vitess"

    def __init__(
        self,
        service: str,
        cluster: str,
        instance: str,
        config_dict: VitessDeploymentConfigDict,
        branch_dict: Optional[BranchDictV2],
        soa_dir: str = DEFAULT_SOA_DIR,
    ) -> None:

        super().__init__(
            cluster=cluster,  # superregion
            instance=instance,  # host-1
            service=service,  # vitess
            soa_dir=soa_dir,
            config_dict=config_dict,
            branch_dict=branch_dict,
        )

    def get_service_name_smartstack(self) -> str:
        """
        We register in vitess.main
        """
        return "vitess_" + self.get_instance()

    def get_nerve_namespace(self) -> str:
        """
        We register in vitess.main
        """
        return "main"

    def get_registrations(self) -> List[str]:
        """
        We register in vitess.main
        """
        registrations = self.config_dict.get("registrations", [])
        for registration in registrations:
            try:
                decompose_job_id(registration)
            except InvalidJobNameError:
                log.error(
                    "Provided registration {} for service "
                    "{} is invalid".format(registration, self.service)
                )

        return registrations or [
            compose_job_id(self.get_service_name_smartstack(), "main")
        ]

    def get_kubernetes_namespace(self) -> str:
        return KUBERNETES_NAMESPACE

    def get_instances(self, with_limit: bool = True) -> int:
        return self.config_dict.get("replicas", 1)

    def get_bounce_method(self) -> str:
        """
        Need to map to a paasta bounce method and crossover is the closest
        """
        return "crossover"

    def get_sanitised_service_name(self) -> str:
        return sanitise_kubernetes_name(self.get_service())

    def get_sanitised_instance_name(self) -> str:
        return sanitise_kubernetes_name(self.get_instance())

    def get_sanitised_deployment_name(self) -> str:
        return self.get_sanitised_instance_name()

    def validate(
        self,
        params: List[str] = [
            "cpus",
            "security",
            "dependencies_reference",
            "deploy_group",
        ],
    ) -> List[str]:
        # Use InstanceConfig to validate shared config keys like cpus and mem
        # TODO: add mem back to this list once we fix PAASTA-15582 and
        # move to using the same units as flink/marathon etc.
        error_msgs = super().validate(params=params)

        if error_msgs:
            name = self.get_instance()
            return [f"{name}: {msg}" for msg in error_msgs]
        else:
            return []


def load_vitess_instance_config(
    service: str,
    instance: str,
    cluster: str,
    load_deployments: bool = True,
    soa_dir: str = DEFAULT_SOA_DIR,
) -> VitessDeploymentConfig:
    general_config = service_configuration_lib.read_service_configuration(
        service, soa_dir=soa_dir
    )
    instance_config = load_service_instance_config(
        service, instance, " vitesscluster", cluster, soa_dir=soa_dir
    )
    general_config = deep_merge_dictionaries(
        overrides=instance_config, defaults=general_config
    )

    branch_dict: Optional[BranchDictV2] = None
    if load_deployments:
        deployments_json = load_v2_deployments_json(service, soa_dir=soa_dir)
        temp_instance_config = VitessDeploymentConfig(
            service=service,
            cluster=cluster,
            instance=instance,
            config_dict=general_config,
            branch_dict=None,
            soa_dir=soa_dir,
        )
        branch = temp_instance_config.get_branch()
        deploy_group = temp_instance_config.get_deploy_group()
        branch_dict = deployments_json.get_branch_dict(service, branch, deploy_group)

    return VitessDeploymentConfig(
        service=service,
        cluster=cluster,
        instance=instance,
        config_dict=general_config,
        branch_dict=branch_dict,
        soa_dir=soa_dir,
    )


# TODO: read this from CRD in service configs
def cr_id(service: str, instance: str) -> Mapping[str, str]:
    return dict(
        group="yelp.com",
        version="v1alpha1",
        namespace=KUBERNETES_NAMESPACE,
        plural="vitess",
        name=sanitised_cr_name(service, instance),
    )
