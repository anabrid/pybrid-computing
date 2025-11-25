import typing
from dataclasses import dataclass, field
from pybrid.redac.entities import Entity, EntityType, EntityClass

@dataclass(kw_only=True)
class ACLPlugin:
    """
    Registers a plugin with its name and type. Note that parameters
    can be passed to the plugin's constructor.
    """
    #: The type of the plugin.
    plugin: str
    #: The plugins' label by which we reference it in the circuit.
    label: str
    #: Parameters passed to the initializer of the plugin.
    parameters: typing.List[float] = field(default_factory=list)

@dataclass(kw_only=True)
class ACLBind:
    """
    Describes the binding between a plugin pins and signals
    within the circuit.
    """
    #: The ACL ondex for the signal (similar tot he LUCIDAC frontplane).
    acl: int
    #: The name of the plugin whose pin is connected to the signal.
    plugin: str
    #: The plugin pin for this connection. Determines the index in the input/output vector.
    pin: int

@dataclass(kw_only=True)
class ACLConfig:
    """
    Describes the connections between the simulated circuits and plugin
    data (= simulating external circuits).
    """  
    #: Defines the plugins, these can be referenced by inputs/outputs.
    plugins: typing.List[ACLPlugin] = field(default_factory=list)
    #: Lists the input connections to the circuit (= outputs of the plugins).
    inputs: typing.List[ACLBind] = field(default_factory=list)
    #: Lists the output connections to the circuit (= inputs of the plugin).
    outputs: typing.List[ACLBind] = field(default_factory=list)

@dataclass(kw_only=True)
class SimConfig:
    """
    This data only concerns runs in the simulator and will be ignored by 
    LUCIDAC/REDAC devices.
    """
    #: Whether to simulate with limits on the integrators, similar to hardware integrators.
    with_limits: bool = True
    #: Lets users overwrite the config's k0 with an arbitrary (e.g. device-unsupported) k0
    k0: typing.Optional[int] = 10_000
    #: Throws away REDAC-like end-of-OP sinks.
    only_module_sinks: bool = False
    #: Sets plugin connections for simulated ACLs.
    acl_config: typing.Optional[ACLConfig] = None

@EntityType.register(EntityClass.OTHER)
@dataclass(kw_only=True)
class SimConfigEntity(Entity, SimConfig):
    """
    Anchors sim config in the "global" entity, with empty path.
    """
    pass