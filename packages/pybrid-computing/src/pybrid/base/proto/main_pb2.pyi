from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Prefix(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    NONE: _ClassVar[Prefix]
    MILLI: _ClassVar[Prefix]
    MICRO: _ClassVar[Prefix]
    NANO: _ClassVar[Prefix]

class RunState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    NEW: _ClassVar[RunState]
    ERROR: _ClassVar[RunState]
    DONE: _ClassVar[RunState]
    QUEUED: _ClassVar[RunState]
    TAKE_OFF: _ClassVar[RunState]
    IC: _ClassVar[RunState]
    OP: _ClassVar[RunState]
    OP_END: _ClassVar[RunState]
    TMP_HALT: _ClassVar[RunState]

class ErrorCode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    None: _ClassVar[ErrorCode]
NONE: Prefix
MILLI: Prefix
MICRO: Prefix
NANO: Prefix
NEW: RunState
ERROR: RunState
DONE: RunState
QUEUED: RunState
TAKE_OFF: RunState
IC: RunState
OP: RunState
OP_END: RunState
TMP_HALT: RunState
None: ErrorCode

class OptionalLane(_message.Message):
    __slots__ = ("idx",)
    IDX_FIELD_NUMBER: _ClassVar[int]
    idx: int
    def __init__(self, idx: _Optional[int] = ...) -> None: ...

class DeviceConfig(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class AdcChannel(_message.Message):
    __slots__ = ("idx", "gain", "offset", "probe")
    IDX_FIELD_NUMBER: _ClassVar[int]
    GAIN_FIELD_NUMBER: _ClassVar[int]
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    PROBE_FIELD_NUMBER: _ClassVar[int]
    idx: int
    gain: float
    offset: float
    probe: int
    def __init__(self, idx: _Optional[int] = ..., gain: _Optional[float] = ..., offset: _Optional[float] = ..., probe: _Optional[int] = ...) -> None: ...

class AdcConfig(_message.Message):
    __slots__ = ("channels",)
    CHANNELS_FIELD_NUMBER: _ClassVar[int]
    channels: _containers.RepeatedCompositeFieldContainer[AdcChannel]
    def __init__(self, channels: _Optional[_Iterable[_Union[AdcChannel, _Mapping]]] = ...) -> None: ...

class ClusterConfig(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class MulConfig(_message.Message):
    __slots__ = ("calibration",)
    class Calibration(_message.Message):
        __slots__ = ("offset_x", "offset_y", "offset_z", "gain")
        OFFSET_X_FIELD_NUMBER: _ClassVar[int]
        OFFSET_Y_FIELD_NUMBER: _ClassVar[int]
        OFFSET_Z_FIELD_NUMBER: _ClassVar[int]
        GAIN_FIELD_NUMBER: _ClassVar[int]
        offset_x: int
        offset_y: int
        offset_z: int
        gain: int
        def __init__(self, offset_x: _Optional[int] = ..., offset_y: _Optional[int] = ..., offset_z: _Optional[int] = ..., gain: _Optional[int] = ...) -> None: ...
    CALIBRATION_FIELD_NUMBER: _ClassVar[int]
    calibration: _containers.RepeatedCompositeFieldContainer[MulConfig.Calibration]
    def __init__(self, calibration: _Optional[_Iterable[_Union[MulConfig.Calibration, _Mapping]]] = ...) -> None: ...

class ShiftHoldConfig(_message.Message):
    __slots__ = ("state",)
    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        TRACK: _ClassVar[ShiftHoldConfig.State]
        TRACK_AT_IC: _ClassVar[ShiftHoldConfig.State]
        INJECT: _ClassVar[ShiftHoldConfig.State]
        GAIN_ZERO_TO_SEVEN: _ClassVar[ShiftHoldConfig.State]
        GAIN_EIGHT_TO_FIFTEEN: _ClassVar[ShiftHoldConfig.State]
        PASSTHROUGH: _ClassVar[ShiftHoldConfig.State]
    TRACK: ShiftHoldConfig.State
    TRACK_AT_IC: ShiftHoldConfig.State
    INJECT: ShiftHoldConfig.State
    GAIN_ZERO_TO_SEVEN: ShiftHoldConfig.State
    GAIN_EIGHT_TO_FIFTEEN: ShiftHoldConfig.State
    PASSTHROUGH: ShiftHoldConfig.State
    STATE_FIELD_NUMBER: _ClassVar[int]
    state: ShiftHoldConfig.State
    def __init__(self, state: _Optional[_Union[ShiftHoldConfig.State, str]] = ...) -> None: ...

class CoefConfig(_message.Message):
    __slots__ = ("elements",)
    class Element(_message.Message):
        __slots__ = ("idx", "factor", "gain_correction")
        IDX_FIELD_NUMBER: _ClassVar[int]
        FACTOR_FIELD_NUMBER: _ClassVar[int]
        GAIN_CORRECTION_FIELD_NUMBER: _ClassVar[int]
        idx: int
        factor: float
        gain_correction: float
        def __init__(self, idx: _Optional[int] = ..., factor: _Optional[float] = ..., gain_correction: _Optional[float] = ...) -> None: ...
    ELEMENTS_FIELD_NUMBER: _ClassVar[int]
    elements: _containers.RepeatedCompositeFieldContainer[CoefConfig.Element]
    def __init__(self, elements: _Optional[_Iterable[_Union[CoefConfig.Element, _Mapping]]] = ...) -> None: ...

class ItorConfig(_message.Message):
    __slots__ = ("elements",)
    class Element(_message.Message):
        __slots__ = ("idx", "ic", "k")
        IDX_FIELD_NUMBER: _ClassVar[int]
        IC_FIELD_NUMBER: _ClassVar[int]
        K_FIELD_NUMBER: _ClassVar[int]
        idx: int
        ic: float
        k: int
        def __init__(self, idx: _Optional[int] = ..., ic: _Optional[float] = ..., k: _Optional[int] = ...) -> None: ...
    ELEMENTS_FIELD_NUMBER: _ClassVar[int]
    elements: _containers.RepeatedCompositeFieldContainer[ItorConfig.Element]
    def __init__(self, elements: _Optional[_Iterable[_Union[ItorConfig.Element, _Mapping]]] = ...) -> None: ...

class LimiterConfig(_message.Message):
    __slots__ = ("elements",)
    class Element(_message.Message):
        __slots__ = ("idx", "enable")
        IDX_FIELD_NUMBER: _ClassVar[int]
        ENABLE_FIELD_NUMBER: _ClassVar[int]
        idx: int
        enable: bool
        def __init__(self, idx: _Optional[int] = ..., enable: _Optional[bool] = ...) -> None: ...
    ELEMENTS_FIELD_NUMBER: _ClassVar[int]
    elements: _containers.RepeatedCompositeFieldContainer[LimiterConfig.Element]
    def __init__(self, elements: _Optional[_Iterable[_Union[LimiterConfig.Element, _Mapping]]] = ...) -> None: ...

class SelectConfig(_message.Message):
    __slots__ = ("connections", "constant", "magnitude")
    class ConstantConfig(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        GROUND: _ClassVar[SelectConfig.ConstantConfig]
        POS_REF: _ClassVar[SelectConfig.ConstantConfig]
        NEG_REF: _ClassVar[SelectConfig.ConstantConfig]
    GROUND: SelectConfig.ConstantConfig
    POS_REF: SelectConfig.ConstantConfig
    NEG_REF: SelectConfig.ConstantConfig
    class Magnitude(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        ONE: _ClassVar[SelectConfig.Magnitude]
        ONE_TENTH: _ClassVar[SelectConfig.Magnitude]
    ONE: SelectConfig.Magnitude
    ONE_TENTH: SelectConfig.Magnitude
    CONNECTIONS_FIELD_NUMBER: _ClassVar[int]
    CONSTANT_FIELD_NUMBER: _ClassVar[int]
    MAGNITUDE_FIELD_NUMBER: _ClassVar[int]
    connections: _containers.RepeatedCompositeFieldContainer[SelectConnectionConfig]
    constant: SelectConfig.ConstantConfig
    magnitude: SelectConfig.Magnitude
    def __init__(self, connections: _Optional[_Iterable[_Union[SelectConnectionConfig, _Mapping]]] = ..., constant: _Optional[_Union[SelectConfig.ConstantConfig, str]] = ..., magnitude: _Optional[_Union[SelectConfig.Magnitude, str]] = ...) -> None: ...

class SelectConnectionConfig(_message.Message):
    __slots__ = ("input", "output")
    INPUT_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_FIELD_NUMBER: _ClassVar[int]
    input: int
    output: int
    def __init__(self, input: _Optional[int] = ..., output: _Optional[int] = ...) -> None: ...

class SumConfig(_message.Message):
    __slots__ = ("connections", "upscales")
    CONNECTIONS_FIELD_NUMBER: _ClassVar[int]
    UPSCALES_FIELD_NUMBER: _ClassVar[int]
    connections: _containers.RepeatedCompositeFieldContainer[SumConnectionConfig]
    upscales: _containers.RepeatedCompositeFieldContainer[UpscaleConfig]
    def __init__(self, connections: _Optional[_Iterable[_Union[SumConnectionConfig, _Mapping]]] = ..., upscales: _Optional[_Iterable[_Union[UpscaleConfig, _Mapping]]] = ...) -> None: ...

class SumConnectionConfig(_message.Message):
    __slots__ = ("inputs", "output")
    INPUTS_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_FIELD_NUMBER: _ClassVar[int]
    inputs: _containers.RepeatedScalarFieldContainer[int]
    output: int
    def __init__(self, inputs: _Optional[_Iterable[int]] = ..., output: _Optional[int] = ...) -> None: ...

class UpscaleConfig(_message.Message):
    __slots__ = ("lane", "enabled")
    LANE_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    lane: int
    enabled: bool
    def __init__(self, lane: _Optional[int] = ..., enabled: _Optional[bool] = ...) -> None: ...

class Address(_message.Message):
    __slots__ = ("data",)
    DATA_FIELD_NUMBER: _ClassVar[int]
    data: bytes
    def __init__(self, data: _Optional[bytes] = ...) -> None: ...

class Mux(_message.Message):
    __slots__ = ("state",)
    STATE_FIELD_NUMBER: _ClassVar[int]
    state: int
    def __init__(self, state: _Optional[int] = ...) -> None: ...

class SwitchConfig(_message.Message):
    __slots__ = ("muxes",)
    MUXES_FIELD_NUMBER: _ClassVar[int]
    muxes: _containers.RepeatedCompositeFieldContainer[Mux]
    def __init__(self, muxes: _Optional[_Iterable[_Union[Mux, _Mapping]]] = ...) -> None: ...

class Trace(_message.Message):
    __slots__ = ("source_node", "source_lane", "sink_node", "sink_lane", "sink_upscaled")
    SOURCE_NODE_FIELD_NUMBER: _ClassVar[int]
    SOURCE_LANE_FIELD_NUMBER: _ClassVar[int]
    SINK_NODE_FIELD_NUMBER: _ClassVar[int]
    SINK_LANE_FIELD_NUMBER: _ClassVar[int]
    SINK_UPSCALED_FIELD_NUMBER: _ClassVar[int]
    source_node: int
    source_lane: int
    sink_node: int
    sink_lane: int
    sink_upscaled: bool
    def __init__(self, source_node: _Optional[int] = ..., source_lane: _Optional[int] = ..., sink_node: _Optional[int] = ..., sink_lane: _Optional[int] = ..., sink_upscaled: _Optional[bool] = ...) -> None: ...

class DependencyInfo(_message.Message):
    __slots__ = ("entity_ids", "traces")
    ENTITY_IDS_FIELD_NUMBER: _ClassVar[int]
    TRACES_FIELD_NUMBER: _ClassVar[int]
    entity_ids: _containers.RepeatedCompositeFieldContainer[EntityId]
    traces: _containers.RepeatedCompositeFieldContainer[Trace]
    def __init__(self, entity_ids: _Optional[_Iterable[_Union[EntityId, _Mapping]]] = ..., traces: _Optional[_Iterable[_Union[Trace, _Mapping]]] = ...) -> None: ...

class BPLSwitchConfig(_message.Message):
    __slots__ = ("muxes",)
    MUXES_FIELD_NUMBER: _ClassVar[int]
    muxes: _containers.RepeatedCompositeFieldContainer[Mux]
    def __init__(self, muxes: _Optional[_Iterable[_Union[Mux, _Mapping]]] = ...) -> None: ...

class CmpConfig(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class SignalGeneratorConfig(_message.Message):
    __slots__ = ("frequency", "phase", "wave_form", "amplitude", "square_voltage_low", "square_voltage_high", "offset", "sleep", "dac_outputs")
    class WaveForm(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        SINE: _ClassVar[SignalGeneratorConfig.WaveForm]
        SINE_AND_SQUARE: _ClassVar[SignalGeneratorConfig.WaveForm]
        TRIANGLE: _ClassVar[SignalGeneratorConfig.WaveForm]
    SINE: SignalGeneratorConfig.WaveForm
    SINE_AND_SQUARE: SignalGeneratorConfig.WaveForm
    TRIANGLE: SignalGeneratorConfig.WaveForm
    FREQUENCY_FIELD_NUMBER: _ClassVar[int]
    PHASE_FIELD_NUMBER: _ClassVar[int]
    WAVE_FORM_FIELD_NUMBER: _ClassVar[int]
    AMPLITUDE_FIELD_NUMBER: _ClassVar[int]
    SQUARE_VOLTAGE_LOW_FIELD_NUMBER: _ClassVar[int]
    SQUARE_VOLTAGE_HIGH_FIELD_NUMBER: _ClassVar[int]
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    SLEEP_FIELD_NUMBER: _ClassVar[int]
    DAC_OUTPUTS_FIELD_NUMBER: _ClassVar[int]
    frequency: float
    phase: float
    wave_form: SignalGeneratorConfig.WaveForm
    amplitude: float
    square_voltage_low: float
    square_voltage_high: float
    offset: float
    sleep: bool
    dac_outputs: _containers.RepeatedScalarFieldContainer[float]
    def __init__(self, frequency: _Optional[float] = ..., phase: _Optional[float] = ..., wave_form: _Optional[_Union[SignalGeneratorConfig.WaveForm, str]] = ..., amplitude: _Optional[float] = ..., square_voltage_low: _Optional[float] = ..., square_voltage_high: _Optional[float] = ..., offset: _Optional[float] = ..., sleep: _Optional[bool] = ..., dac_outputs: _Optional[_Iterable[float]] = ...) -> None: ...

class FrontPanelConfig(_message.Message):
    __slots__ = ("leds",)
    LEDS_FIELD_NUMBER: _ClassVar[int]
    leds: int
    def __init__(self, leds: _Optional[int] = ...) -> None: ...

class FrontPanelIOConfig(_message.Message):
    __slots__ = ("io_modes",)
    class FrontPanelIOMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        ANALOG_OUT: _ClassVar[FrontPanelIOConfig.FrontPanelIOMode]
        ANALOG_IN: _ClassVar[FrontPanelIOConfig.FrontPanelIOMode]
        DIGITAL_OUT: _ClassVar[FrontPanelIOConfig.FrontPanelIOMode]
        DIGITAL_IN: _ClassVar[FrontPanelIOConfig.FrontPanelIOMode]
    ANALOG_OUT: FrontPanelIOConfig.FrontPanelIOMode
    ANALOG_IN: FrontPanelIOConfig.FrontPanelIOMode
    DIGITAL_OUT: FrontPanelIOConfig.FrontPanelIOMode
    DIGITAL_IN: FrontPanelIOConfig.FrontPanelIOMode
    IO_MODES_FIELD_NUMBER: _ClassVar[int]
    io_modes: _containers.RepeatedScalarFieldContainer[FrontPanelIOConfig.FrontPanelIOMode]
    def __init__(self, io_modes: _Optional[_Iterable[_Union[FrontPanelIOConfig.FrontPanelIOMode, str]]] = ...) -> None: ...

class ACLPinSignal(_message.Message):
    __slots__ = ("signal", "pin")
    SIGNAL_FIELD_NUMBER: _ClassVar[int]
    PIN_FIELD_NUMBER: _ClassVar[int]
    signal: str
    pin: int
    def __init__(self, signal: _Optional[str] = ..., pin: _Optional[int] = ...) -> None: ...

class PortConfig(_message.Message):
    __slots__ = ("states", "inputs", "outputs")
    class AclState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        INTERNAL: _ClassVar[PortConfig.AclState]
        EXTERNAL: _ClassVar[PortConfig.AclState]
    INTERNAL: PortConfig.AclState
    EXTERNAL: PortConfig.AclState
    STATES_FIELD_NUMBER: _ClassVar[int]
    INPUTS_FIELD_NUMBER: _ClassVar[int]
    OUTPUTS_FIELD_NUMBER: _ClassVar[int]
    states: _containers.RepeatedScalarFieldContainer[PortConfig.AclState]
    inputs: _containers.RepeatedCompositeFieldContainer[ACLPinSignal]
    outputs: _containers.RepeatedCompositeFieldContainer[ACLPinSignal]
    def __init__(self, states: _Optional[_Iterable[_Union[PortConfig.AclState, str]]] = ..., inputs: _Optional[_Iterable[_Union[ACLPinSignal, _Mapping]]] = ..., outputs: _Optional[_Iterable[_Union[ACLPinSignal, _Mapping]]] = ...) -> None: ...

class BackpanelConfig(_message.Message):
    __slots__ = ("backpanel_id", "backpanel_slot", "is_valid", "is_isolated")
    BACKPANEL_ID_FIELD_NUMBER: _ClassVar[int]
    BACKPANEL_SLOT_FIELD_NUMBER: _ClassVar[int]
    IS_VALID_FIELD_NUMBER: _ClassVar[int]
    IS_ISOLATED_FIELD_NUMBER: _ClassVar[int]
    backpanel_id: int
    backpanel_slot: int
    is_valid: bool
    is_isolated: bool
    def __init__(self, backpanel_id: _Optional[int] = ..., backpanel_slot: _Optional[int] = ..., is_valid: _Optional[bool] = ..., is_isolated: _Optional[bool] = ...) -> None: ...

class IpLookupTable(_message.Message):
    __slots__ = ("entries",)
    class Entry(_message.Message):
        __slots__ = ("entity_id", "address")
        ENTITY_ID_FIELD_NUMBER: _ClassVar[int]
        ADDRESS_FIELD_NUMBER: _ClassVar[int]
        entity_id: EntityId
        address: Address
        def __init__(self, entity_id: _Optional[_Union[EntityId, _Mapping]] = ..., address: _Optional[_Union[Address, _Mapping]] = ...) -> None: ...
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    entries: _containers.RepeatedCompositeFieldContainer[IpLookupTable.Entry]
    def __init__(self, entries: _Optional[_Iterable[_Union[IpLookupTable.Entry, _Mapping]]] = ...) -> None: ...

class EntitySpecification(_message.Message):
    __slots__ = ("entity",)
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    entity: Entity
    def __init__(self, entity: _Optional[_Union[Entity, _Mapping]] = ...) -> None: ...

class Item(_message.Message):
    __slots__ = ("entity", "adc_config", "cluster_config", "mul_config", "shift_hold_config", "coef_config", "itor_config", "select_config", "sum_config", "switch_config", "device_config", "limiter_config", "front_panel_config", "signal_generator_config", "port_config", "backpanel_config", "bpl_switch_config", "cmp_config", "entity_specification", "dependency_info", "ip_lookup_table", "front_panel_io_config", "sim_config")
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    ADC_CONFIG_FIELD_NUMBER: _ClassVar[int]
    CLUSTER_CONFIG_FIELD_NUMBER: _ClassVar[int]
    MUL_CONFIG_FIELD_NUMBER: _ClassVar[int]
    SHIFT_HOLD_CONFIG_FIELD_NUMBER: _ClassVar[int]
    COEF_CONFIG_FIELD_NUMBER: _ClassVar[int]
    ITOR_CONFIG_FIELD_NUMBER: _ClassVar[int]
    SELECT_CONFIG_FIELD_NUMBER: _ClassVar[int]
    SUM_CONFIG_FIELD_NUMBER: _ClassVar[int]
    SWITCH_CONFIG_FIELD_NUMBER: _ClassVar[int]
    DEVICE_CONFIG_FIELD_NUMBER: _ClassVar[int]
    LIMITER_CONFIG_FIELD_NUMBER: _ClassVar[int]
    FRONT_PANEL_CONFIG_FIELD_NUMBER: _ClassVar[int]
    SIGNAL_GENERATOR_CONFIG_FIELD_NUMBER: _ClassVar[int]
    PORT_CONFIG_FIELD_NUMBER: _ClassVar[int]
    BACKPANEL_CONFIG_FIELD_NUMBER: _ClassVar[int]
    BPL_SWITCH_CONFIG_FIELD_NUMBER: _ClassVar[int]
    CMP_CONFIG_FIELD_NUMBER: _ClassVar[int]
    ENTITY_SPECIFICATION_FIELD_NUMBER: _ClassVar[int]
    DEPENDENCY_INFO_FIELD_NUMBER: _ClassVar[int]
    IP_LOOKUP_TABLE_FIELD_NUMBER: _ClassVar[int]
    FRONT_PANEL_IO_CONFIG_FIELD_NUMBER: _ClassVar[int]
    SIM_CONFIG_FIELD_NUMBER: _ClassVar[int]
    entity: EntityId
    adc_config: AdcConfig
    cluster_config: ClusterConfig
    mul_config: MulConfig
    shift_hold_config: ShiftHoldConfig
    coef_config: CoefConfig
    itor_config: ItorConfig
    select_config: SelectConfig
    sum_config: SumConfig
    switch_config: SwitchConfig
    device_config: DeviceConfig
    limiter_config: LimiterConfig
    front_panel_config: FrontPanelConfig
    signal_generator_config: SignalGeneratorConfig
    port_config: PortConfig
    backpanel_config: BackpanelConfig
    bpl_switch_config: BPLSwitchConfig
    cmp_config: CmpConfig
    entity_specification: EntitySpecification
    dependency_info: DependencyInfo
    ip_lookup_table: IpLookupTable
    front_panel_io_config: FrontPanelIOConfig
    sim_config: SimConfig
    def __init__(self, entity: _Optional[_Union[EntityId, _Mapping]] = ..., adc_config: _Optional[_Union[AdcConfig, _Mapping]] = ..., cluster_config: _Optional[_Union[ClusterConfig, _Mapping]] = ..., mul_config: _Optional[_Union[MulConfig, _Mapping]] = ..., shift_hold_config: _Optional[_Union[ShiftHoldConfig, _Mapping]] = ..., coef_config: _Optional[_Union[CoefConfig, _Mapping]] = ..., itor_config: _Optional[_Union[ItorConfig, _Mapping]] = ..., select_config: _Optional[_Union[SelectConfig, _Mapping]] = ..., sum_config: _Optional[_Union[SumConfig, _Mapping]] = ..., switch_config: _Optional[_Union[SwitchConfig, _Mapping]] = ..., device_config: _Optional[_Union[DeviceConfig, _Mapping]] = ..., limiter_config: _Optional[_Union[LimiterConfig, _Mapping]] = ..., front_panel_config: _Optional[_Union[FrontPanelConfig, _Mapping]] = ..., signal_generator_config: _Optional[_Union[SignalGeneratorConfig, _Mapping]] = ..., port_config: _Optional[_Union[PortConfig, _Mapping]] = ..., backpanel_config: _Optional[_Union[BackpanelConfig, _Mapping]] = ..., bpl_switch_config: _Optional[_Union[BPLSwitchConfig, _Mapping]] = ..., cmp_config: _Optional[_Union[CmpConfig, _Mapping]] = ..., entity_specification: _Optional[_Union[EntitySpecification, _Mapping]] = ..., dependency_info: _Optional[_Union[DependencyInfo, _Mapping]] = ..., ip_lookup_table: _Optional[_Union[IpLookupTable, _Mapping]] = ..., front_panel_io_config: _Optional[_Union[FrontPanelIOConfig, _Mapping]] = ..., sim_config: _Optional[_Union[SimConfig, _Mapping]] = ...) -> None: ...

class EntityId(_message.Message):
    __slots__ = ("path",)
    PATH_FIELD_NUMBER: _ClassVar[int]
    path: str
    def __init__(self, path: _Optional[str] = ...) -> None: ...

class DescribeCommand(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ResetCommand(_message.Message):
    __slots__ = ("entity", "keep_calibration", "overload_reset", "circuit_reset", "sync")
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    KEEP_CALIBRATION_FIELD_NUMBER: _ClassVar[int]
    OVERLOAD_RESET_FIELD_NUMBER: _ClassVar[int]
    CIRCUIT_RESET_FIELD_NUMBER: _ClassVar[int]
    SYNC_FIELD_NUMBER: _ClassVar[int]
    entity: EntityId
    keep_calibration: bool
    overload_reset: bool
    circuit_reset: bool
    sync: bool
    def __init__(self, entity: _Optional[_Union[EntityId, _Mapping]] = ..., keep_calibration: _Optional[bool] = ..., overload_reset: _Optional[bool] = ..., circuit_reset: _Optional[bool] = ..., sync: _Optional[bool] = ...) -> None: ...

class ExtractCommand(_message.Message):
    __slots__ = ("entity", "recursive", "specification", "configuration", "calibration")
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    RECURSIVE_FIELD_NUMBER: _ClassVar[int]
    SPECIFICATION_FIELD_NUMBER: _ClassVar[int]
    CONFIGURATION_FIELD_NUMBER: _ClassVar[int]
    CALIBRATION_FIELD_NUMBER: _ClassVar[int]
    entity: EntityId
    recursive: bool
    specification: bool
    configuration: bool
    calibration: bool
    def __init__(self, entity: _Optional[_Union[EntityId, _Mapping]] = ..., recursive: _Optional[bool] = ..., specification: _Optional[bool] = ..., configuration: _Optional[bool] = ..., calibration: _Optional[bool] = ...) -> None: ...

class ConfigCommand(_message.Message):
    __slots__ = ("module", "reset_before", "sh_kludge")
    MODULE_FIELD_NUMBER: _ClassVar[int]
    RESET_BEFORE_FIELD_NUMBER: _ClassVar[int]
    SH_KLUDGE_FIELD_NUMBER: _ClassVar[int]
    module: Module
    reset_before: bool
    sh_kludge: bool
    def __init__(self, module: _Optional[_Union[Module, _Mapping]] = ..., reset_before: _Optional[bool] = ..., sh_kludge: _Optional[bool] = ...) -> None: ...

class ACLPlugin(_message.Message):
    __slots__ = ("plugin", "label", "parameters")
    PLUGIN_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    PARAMETERS_FIELD_NUMBER: _ClassVar[int]
    plugin: str
    label: str
    parameters: _containers.RepeatedScalarFieldContainer[float]
    def __init__(self, plugin: _Optional[str] = ..., label: _Optional[str] = ..., parameters: _Optional[_Iterable[float]] = ...) -> None: ...

class ACLWire(_message.Message):
    __slots__ = ("source", "target")
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    source: ACLPlug
    target: ACLPlug
    def __init__(self, source: _Optional[_Union[ACLPlug, _Mapping]] = ..., target: _Optional[_Union[ACLPlug, _Mapping]] = ...) -> None: ...

class ACLPlug(_message.Message):
    __slots__ = ("entity_id", "kind")
    class Kind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        Device: _ClassVar[ACLPlug.Kind]
        Plugin: _ClassVar[ACLPlug.Kind]
    Device: ACLPlug.Kind
    Plugin: ACLPlug.Kind
    ENTITY_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    entity_id: EntityId
    kind: ACLPlug.Kind
    def __init__(self, entity_id: _Optional[_Union[EntityId, _Mapping]] = ..., kind: _Optional[_Union[ACLPlug.Kind, str]] = ...) -> None: ...

class ACLConfig(_message.Message):
    __slots__ = ("plugins", "wires")
    PLUGINS_FIELD_NUMBER: _ClassVar[int]
    WIRES_FIELD_NUMBER: _ClassVar[int]
    plugins: _containers.RepeatedCompositeFieldContainer[ACLPlugin]
    wires: _containers.RepeatedCompositeFieldContainer[ACLWire]
    def __init__(self, plugins: _Optional[_Iterable[_Union[ACLPlugin, _Mapping]]] = ..., wires: _Optional[_Iterable[_Union[ACLWire, _Mapping]]] = ...) -> None: ...

class SimConfig(_message.Message):
    __slots__ = ("k0", "with_limits", "only_module_sinks", "acl_config")
    K0_FIELD_NUMBER: _ClassVar[int]
    WITH_LIMITS_FIELD_NUMBER: _ClassVar[int]
    ONLY_MODULE_SINKS_FIELD_NUMBER: _ClassVar[int]
    ACL_CONFIG_FIELD_NUMBER: _ClassVar[int]
    k0: int
    with_limits: bool
    only_module_sinks: bool
    acl_config: ACLConfig
    def __init__(self, k0: _Optional[int] = ..., with_limits: _Optional[bool] = ..., only_module_sinks: _Optional[bool] = ..., acl_config: _Optional[_Union[ACLConfig, _Mapping]] = ...) -> None: ...

class Module(_message.Message):
    __slots__ = ("items",)
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[Item]
    def __init__(self, items: _Optional[_Iterable[_Union[Item, _Mapping]]] = ...) -> None: ...

class DescribeBundle(_message.Message):
    __slots__ = ("entities",)
    ENTITIES_FIELD_NUMBER: _ClassVar[int]
    entities: _containers.RepeatedCompositeFieldContainer[Module]
    def __init__(self, entities: _Optional[_Iterable[_Union[Module, _Mapping]]] = ...) -> None: ...

class Time(_message.Message):
    __slots__ = ("value", "prefix")
    VALUE_FIELD_NUMBER: _ClassVar[int]
    PREFIX_FIELD_NUMBER: _ClassVar[int]
    value: int
    prefix: Prefix
    def __init__(self, value: _Optional[int] = ..., prefix: _Optional[_Union[Prefix, str]] = ...) -> None: ...

class Temperature(_message.Message):
    __slots__ = ("value", "unit")
    class Unit(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        NONE: _ClassVar[Temperature.Unit]
        CELSIUS: _ClassVar[Temperature.Unit]
        FAHRENHEIT: _ClassVar[Temperature.Unit]
        KELVIN: _ClassVar[Temperature.Unit]
    NONE: Temperature.Unit
    CELSIUS: Temperature.Unit
    FAHRENHEIT: Temperature.Unit
    KELVIN: Temperature.Unit
    VALUE_FIELD_NUMBER: _ClassVar[int]
    UNIT_FIELD_NUMBER: _ClassVar[int]
    value: float
    unit: Temperature.Unit
    def __init__(self, value: _Optional[float] = ..., unit: _Optional[_Union[Temperature.Unit, str]] = ...) -> None: ...

class RunConfig(_message.Message):
    __slots__ = ("ic_time", "op_time", "halt_on_overload", "streaming", "repetitive", "write_run_state_changes")
    IC_TIME_FIELD_NUMBER: _ClassVar[int]
    OP_TIME_FIELD_NUMBER: _ClassVar[int]
    HALT_ON_OVERLOAD_FIELD_NUMBER: _ClassVar[int]
    STREAMING_FIELD_NUMBER: _ClassVar[int]
    REPETITIVE_FIELD_NUMBER: _ClassVar[int]
    WRITE_RUN_STATE_CHANGES_FIELD_NUMBER: _ClassVar[int]
    ic_time: Time
    op_time: Time
    halt_on_overload: bool
    streaming: bool
    repetitive: bool
    write_run_state_changes: bool
    def __init__(self, ic_time: _Optional[_Union[Time, _Mapping]] = ..., op_time: _Optional[_Union[Time, _Mapping]] = ..., halt_on_overload: _Optional[bool] = ..., streaming: _Optional[bool] = ..., repetitive: _Optional[bool] = ..., write_run_state_changes: _Optional[bool] = ...) -> None: ...

class DaqConfig(_message.Message):
    __slots__ = ("num_channels", "sample_rate", "sample_op", "sample_op_end")
    NUM_CHANNELS_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_RATE_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_OP_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_OP_END_FIELD_NUMBER: _ClassVar[int]
    num_channels: int
    sample_rate: int
    sample_op: bool
    sample_op_end: bool
    def __init__(self, num_channels: _Optional[int] = ..., sample_rate: _Optional[int] = ..., sample_op: _Optional[bool] = ..., sample_op_end: _Optional[bool] = ...) -> None: ...

class SyncConfig(_message.Message):
    __slots__ = ("enabled", "master", "group")
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    MASTER_FIELD_NUMBER: _ClassVar[int]
    GROUP_FIELD_NUMBER: _ClassVar[int]
    enabled: bool
    master: EntityId
    group: int
    def __init__(self, enabled: _Optional[bool] = ..., master: _Optional[_Union[EntityId, _Mapping]] = ..., group: _Optional[int] = ...) -> None: ...

class CalibrationConfig(_message.Message):
    __slots__ = ("leader", "math", "gain", "offset")
    class Kind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        Disabled: _ClassVar[CalibrationConfig.Kind]
        Enabled: _ClassVar[CalibrationConfig.Kind]
    Disabled: CalibrationConfig.Kind
    Enabled: CalibrationConfig.Kind
    LEADER_FIELD_NUMBER: _ClassVar[int]
    MATH_FIELD_NUMBER: _ClassVar[int]
    GAIN_FIELD_NUMBER: _ClassVar[int]
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    leader: EntityId
    math: CalibrationConfig.Kind
    gain: CalibrationConfig.Kind
    offset: CalibrationConfig.Kind
    def __init__(self, leader: _Optional[_Union[EntityId, _Mapping]] = ..., math: _Optional[_Union[CalibrationConfig.Kind, str]] = ..., gain: _Optional[_Union[CalibrationConfig.Kind, str]] = ..., offset: _Optional[_Union[CalibrationConfig.Kind, str]] = ...) -> None: ...

class UdpDataStreamingCommand(_message.Message):
    __slots__ = ("port",)
    PORT_FIELD_NUMBER: _ClassVar[int]
    port: int
    def __init__(self, port: _Optional[int] = ...) -> None: ...

class UdpDataStreamingRefusedResponse(_message.Message):
    __slots__ = ("reason",)
    REASON_FIELD_NUMBER: _ClassVar[int]
    reason: str
    def __init__(self, reason: _Optional[str] = ...) -> None: ...

class StartRunCommand(_message.Message):
    __slots__ = ("run", "run_config", "daq_config", "sync_config", "end_repetitive", "clear_queue")
    RUN_FIELD_NUMBER: _ClassVar[int]
    RUN_CONFIG_FIELD_NUMBER: _ClassVar[int]
    DAQ_CONFIG_FIELD_NUMBER: _ClassVar[int]
    SYNC_CONFIG_FIELD_NUMBER: _ClassVar[int]
    END_REPETITIVE_FIELD_NUMBER: _ClassVar[int]
    CLEAR_QUEUE_FIELD_NUMBER: _ClassVar[int]
    run: Run
    run_config: RunConfig
    daq_config: DaqConfig
    sync_config: SyncConfig
    end_repetitive: bool
    clear_queue: bool
    def __init__(self, run: _Optional[_Union[Run, _Mapping]] = ..., run_config: _Optional[_Union[RunConfig, _Mapping]] = ..., daq_config: _Optional[_Union[DaqConfig, _Mapping]] = ..., sync_config: _Optional[_Union[SyncConfig, _Mapping]] = ..., end_repetitive: _Optional[bool] = ..., clear_queue: _Optional[bool] = ...) -> None: ...

class StopRunCommand(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class StandByCommand(_message.Message):
    __slots__ = ("standby", "hack_pwm_ramp")
    STANDBY_FIELD_NUMBER: _ClassVar[int]
    HACK_PWM_RAMP_FIELD_NUMBER: _ClassVar[int]
    standby: bool
    hack_pwm_ramp: bool
    def __init__(self, standby: _Optional[bool] = ..., hack_pwm_ramp: _Optional[bool] = ...) -> None: ...

class ManualControlCommand(_message.Message):
    __slots__ = ("to",)
    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        IC: _ClassVar[ManualControlCommand.State]
        OP: _ClassVar[ManualControlCommand.State]
        HALT: _ClassVar[ManualControlCommand.State]
        MINION: _ClassVar[ManualControlCommand.State]
    IC: ManualControlCommand.State
    OP: ManualControlCommand.State
    HALT: ManualControlCommand.State
    MINION: ManualControlCommand.State
    TO_FIELD_NUMBER: _ClassVar[int]
    to: ManualControlCommand.State
    def __init__(self, to: _Optional[_Union[ManualControlCommand.State, str]] = ...) -> None: ...

class PingCommand(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class RegisterExternalEntitiesCommand(_message.Message):
    __slots__ = ("entities",)
    class EntitiesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: Address
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[Address, _Mapping]] = ...) -> None: ...
    ENTITIES_FIELD_NUMBER: _ClassVar[int]
    entities: _containers.MessageMap[str, Address]
    def __init__(self, entities: _Optional[_Mapping[str, Address]] = ...) -> None: ...

class SyslogCommand(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class SystemStatsCommand(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Version(_message.Message):
    __slots__ = ("major", "minor", "patch")
    MAJOR_FIELD_NUMBER: _ClassVar[int]
    MINOR_FIELD_NUMBER: _ClassVar[int]
    PATCH_FIELD_NUMBER: _ClassVar[int]
    major: int
    minor: int
    patch: int
    def __init__(self, major: _Optional[int] = ..., minor: _Optional[int] = ..., patch: _Optional[int] = ...) -> None: ...

class CarrierLocationV0(_message.Message):
    __slots__ = ("stack", "carrier")
    STACK_FIELD_NUMBER: _ClassVar[int]
    CARRIER_FIELD_NUMBER: _ClassVar[int]
    stack: int
    carrier: int
    def __init__(self, stack: _Optional[int] = ..., carrier: _Optional[int] = ...) -> None: ...

class Entity(_message.Message):
    __slots__ = ("id", "class_", "type", "variant", "version", "eui", "children", "location_v0")
    class Class(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        UNKNOWN: _ClassVar[Entity.Class]
        CARRIER: _ClassVar[Entity.Class]
        CLUSTER: _ClassVar[Entity.Class]
        M_BLOCK: _ClassVar[Entity.Class]
        U_BLOCK: _ClassVar[Entity.Class]
        C_BLOCK: _ClassVar[Entity.Class]
        I_BLOCK: _ClassVar[Entity.Class]
        SH_BLOCK: _ClassVar[Entity.Class]
        FRONT_PANEL: _ClassVar[Entity.Class]
        CTRL_BLOCK: _ClassVar[Entity.Class]
        T_BLOCK: _ClassVar[Entity.Class]
        BACK_PANEL: _ClassVar[Entity.Class]
        BACK_PANEL_T_BLOCK: _ClassVar[Entity.Class]
        DEVICE: _ClassVar[Entity.Class]
    UNKNOWN: Entity.Class
    CARRIER: Entity.Class
    CLUSTER: Entity.Class
    M_BLOCK: Entity.Class
    U_BLOCK: Entity.Class
    C_BLOCK: Entity.Class
    I_BLOCK: Entity.Class
    SH_BLOCK: Entity.Class
    FRONT_PANEL: Entity.Class
    CTRL_BLOCK: Entity.Class
    T_BLOCK: Entity.Class
    BACK_PANEL: Entity.Class
    BACK_PANEL_T_BLOCK: Entity.Class
    DEVICE: Entity.Class
    ID_FIELD_NUMBER: _ClassVar[int]
    CLASS__FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    VARIANT_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    EUI_FIELD_NUMBER: _ClassVar[int]
    CHILDREN_FIELD_NUMBER: _ClassVar[int]
    LOCATION_V0_FIELD_NUMBER: _ClassVar[int]
    id: str
    class_: Entity.Class
    type: int
    variant: int
    version: Version
    eui: str
    children: _containers.RepeatedCompositeFieldContainer[Entity]
    location_v0: CarrierLocationV0
    def __init__(self, id: _Optional[str] = ..., class_: _Optional[_Union[Entity.Class, str]] = ..., type: _Optional[int] = ..., variant: _Optional[int] = ..., version: _Optional[_Union[Version, _Mapping]] = ..., eui: _Optional[str] = ..., children: _Optional[_Iterable[_Union[Entity, _Mapping]]] = ..., location_v0: _Optional[_Union[CarrierLocationV0, _Mapping]] = ...) -> None: ...

class ResetResponse(_message.Message):
    __slots__ = ("entity",)
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    entity: EntityId
    def __init__(self, entity: _Optional[_Union[EntityId, _Mapping]] = ...) -> None: ...

class ExtractResponse(_message.Message):
    __slots__ = ("module",)
    MODULE_FIELD_NUMBER: _ClassVar[int]
    module: Module
    def __init__(self, module: _Optional[_Union[Module, _Mapping]] = ...) -> None: ...

class ConfigResponse(_message.Message):
    __slots__ = ("entity",)
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    entity: EntityId
    def __init__(self, entity: _Optional[_Union[EntityId, _Mapping]] = ...) -> None: ...

class StartRunResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class RunStateChangeMessage(_message.Message):
    __slots__ = ("run", "old", "new_", "time", "reason", "entity")
    RUN_FIELD_NUMBER: _ClassVar[int]
    OLD_FIELD_NUMBER: _ClassVar[int]
    NEW__FIELD_NUMBER: _ClassVar[int]
    TIME_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    run: Run
    old: RunState
    new_: RunState
    time: Time
    reason: str
    entity: EntityId
    def __init__(self, run: _Optional[_Union[Run, _Mapping]] = ..., old: _Optional[_Union[RunState, str]] = ..., new_: _Optional[_Union[RunState, str]] = ..., time: _Optional[_Union[Time, _Mapping]] = ..., reason: _Optional[str] = ..., entity: _Optional[_Union[EntityId, _Mapping]] = ...) -> None: ...

class IntegerType(_message.Message):
    __slots__ = ("signess", "bitwidth")
    class Signedness(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        Signed: _ClassVar[IntegerType.Signedness]
        Unsigned: _ClassVar[IntegerType.Signedness]
    Signed: IntegerType.Signedness
    Unsigned: IntegerType.Signedness
    SIGNESS_FIELD_NUMBER: _ClassVar[int]
    BITWIDTH_FIELD_NUMBER: _ClassVar[int]
    signess: IntegerType.Signedness
    bitwidth: int
    def __init__(self, signess: _Optional[_Union[IntegerType.Signedness, str]] = ..., bitwidth: _Optional[int] = ...) -> None: ...

class FloatType(_message.Message):
    __slots__ = ("bitwidth",)
    BITWIDTH_FIELD_NUMBER: _ClassVar[int]
    bitwidth: int
    def __init__(self, bitwidth: _Optional[int] = ...) -> None: ...

class DataType(_message.Message):
    __slots__ = ("float_", "integer")
    FLOAT__FIELD_NUMBER: _ClassVar[int]
    INTEGER_FIELD_NUMBER: _ClassVar[int]
    float_: FloatType
    integer: IntegerType
    def __init__(self, float_: _Optional[_Union[FloatType, _Mapping]] = ..., integer: _Optional[_Union[IntegerType, _Mapping]] = ...) -> None: ...

class DaqData(_message.Message):
    __slots__ = ("data", "type", "channels", "sample_count", "channel_stride")
    DATA_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    CHANNELS_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_COUNT_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_STRIDE_FIELD_NUMBER: _ClassVar[int]
    data: bytes
    type: DataType
    channels: _containers.RepeatedCompositeFieldContainer[AdcChannel]
    sample_count: int
    channel_stride: int
    def __init__(self, data: _Optional[bytes] = ..., type: _Optional[_Union[DataType, _Mapping]] = ..., channels: _Optional[_Iterable[_Union[AdcChannel, _Mapping]]] = ..., sample_count: _Optional[int] = ..., channel_stride: _Optional[int] = ...) -> None: ...

class Run(_message.Message):
    __slots__ = ("id", "chunk")
    ID_FIELD_NUMBER: _ClassVar[int]
    CHUNK_FIELD_NUMBER: _ClassVar[int]
    id: str
    chunk: int
    def __init__(self, id: _Optional[str] = ..., chunk: _Optional[int] = ...) -> None: ...

class RunDataMessage(_message.Message):
    __slots__ = ("run", "entity", "data")
    RUN_FIELD_NUMBER: _ClassVar[int]
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    run: Run
    entity: EntityId
    data: DaqData
    def __init__(self, run: _Optional[_Union[Run, _Mapping]] = ..., entity: _Optional[_Union[EntityId, _Mapping]] = ..., data: _Optional[_Union[DaqData, _Mapping]] = ...) -> None: ...

class RunDataEndMessage(_message.Message):
    __slots__ = ("run", "entity", "data")
    RUN_FIELD_NUMBER: _ClassVar[int]
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    run: Run
    entity: EntityId
    data: DaqData
    def __init__(self, run: _Optional[_Union[Run, _Mapping]] = ..., entity: _Optional[_Union[EntityId, _Mapping]] = ..., data: _Optional[_Union[DaqData, _Mapping]] = ...) -> None: ...

class PingResponse(_message.Message):
    __slots__ = ("micros",)
    MICROS_FIELD_NUMBER: _ClassVar[int]
    micros: int
    def __init__(self, micros: _Optional[int] = ...) -> None: ...

class FirmwareBuild(_message.Message):
    __slots__ = ("entries",)
    class EntriesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    entries: _containers.ScalarMap[str, str]
    def __init__(self, entries: _Optional[_Mapping[str, str]] = ...) -> None: ...

class FirmwareImage(_message.Message):
    __slots__ = ("size", "sha256sum")
    SIZE_FIELD_NUMBER: _ClassVar[int]
    SHA256SUM_FIELD_NUMBER: _ClassVar[int]
    size: int
    sha256sum: str
    def __init__(self, size: _Optional[int] = ..., sha256sum: _Optional[str] = ...) -> None: ...

class GetSystemIdentResponse(_message.Message):
    __slots__ = ("mac", "fw_build", "fw_image")
    MAC_FIELD_NUMBER: _ClassVar[int]
    FW_BUILD_FIELD_NUMBER: _ClassVar[int]
    FW_IMAGE_FIELD_NUMBER: _ClassVar[int]
    mac: str
    fw_build: FirmwareBuild
    fw_image: FirmwareImage
    def __init__(self, mac: _Optional[str] = ..., fw_build: _Optional[_Union[FirmwareBuild, _Mapping]] = ..., fw_image: _Optional[_Union[FirmwareImage, _Mapping]] = ...) -> None: ...

class SyslogResponse(_message.Message):
    __slots__ = ("is_active", "max_size", "entries")
    IS_ACTIVE_FIELD_NUMBER: _ClassVar[int]
    MAX_SIZE_FIELD_NUMBER: _ClassVar[int]
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    is_active: bool
    max_size: int
    entries: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, is_active: _Optional[bool] = ..., max_size: _Optional[int] = ..., entries: _Optional[_Iterable[str]] = ...) -> None: ...

class PerformanceCounters(_message.Message):
    __slots__ = ("total_ic_time_us", "total_op_time_us", "total_halt_time_us", "total_number_of_runs")
    TOTAL_IC_TIME_US_FIELD_NUMBER: _ClassVar[int]
    TOTAL_OP_TIME_US_FIELD_NUMBER: _ClassVar[int]
    TOTAL_HALT_TIME_US_FIELD_NUMBER: _ClassVar[int]
    TOTAL_NUMBER_OF_RUNS_FIELD_NUMBER: _ClassVar[int]
    total_ic_time_us: int
    total_op_time_us: int
    total_halt_time_us: int
    total_number_of_runs: int
    def __init__(self, total_ic_time_us: _Optional[int] = ..., total_op_time_us: _Optional[int] = ..., total_halt_time_us: _Optional[int] = ..., total_number_of_runs: _Optional[int] = ...) -> None: ...

class SystemStatsResponse(_message.Message):
    __slots__ = ("perf_counters",)
    PERF_COUNTERS_FIELD_NUMBER: _ClassVar[int]
    perf_counters: PerformanceCounters
    def __init__(self, perf_counters: _Optional[_Union[PerformanceCounters, _Mapping]] = ...) -> None: ...

class ReadSystemIdentCommand(_message.Message):
    __slots__ = ("read_from_eeprom",)
    READ_FROM_EEPROM_FIELD_NUMBER: _ClassVar[int]
    read_from_eeprom: bool
    def __init__(self, read_from_eeprom: _Optional[bool] = ...) -> None: ...

class ReadSystemIdentResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ResetSystemIdentCommand(_message.Message):
    __slots__ = ("write_to_hardware",)
    WRITE_TO_HARDWARE_FIELD_NUMBER: _ClassVar[int]
    write_to_hardware: bool
    def __init__(self, write_to_hardware: _Optional[bool] = ...) -> None: ...

class ResetSystemIdentResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class WriteSystemIdentCommand(_message.Message):
    __slots__ = ("vendor",)
    VENDOR_FIELD_NUMBER: _ClassVar[int]
    vendor: Vendor
    def __init__(self, vendor: _Optional[_Union[Vendor, _Mapping]] = ...) -> None: ...

class Vendor(_message.Message):
    __slots__ = ("serial_number", "serial_uuid", "default_admin_password", "default_user_password")
    SERIAL_NUMBER_FIELD_NUMBER: _ClassVar[int]
    SERIAL_UUID_FIELD_NUMBER: _ClassVar[int]
    DEFAULT_ADMIN_PASSWORD_FIELD_NUMBER: _ClassVar[int]
    DEFAULT_USER_PASSWORD_FIELD_NUMBER: _ClassVar[int]
    serial_number: int
    serial_uuid: str
    default_admin_password: str
    default_user_password: str
    def __init__(self, serial_number: _Optional[int] = ..., serial_uuid: _Optional[str] = ..., default_admin_password: _Optional[str] = ..., default_user_password: _Optional[str] = ...) -> None: ...

class WriteSystemIdentResponse(_message.Message):
    __slots__ = ("valid",)
    VALID_FIELD_NUMBER: _ClassVar[int]
    valid: bool
    def __init__(self, valid: _Optional[bool] = ...) -> None: ...

class GetSystemIdentCommand(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CalibrationCommand(_message.Message):
    __slots__ = ("config",)
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    config: CalibrationConfig
    def __init__(self, config: _Optional[_Union[CalibrationConfig, _Mapping]] = ...) -> None: ...

class CalibrationResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CalibrateInitCommand(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CalibrateFinalizeCommand(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CalibrateOffsetCommand(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CalibrateLaneCommand(_message.Message):
    __slots__ = ("lane",)
    LANE_FIELD_NUMBER: _ClassVar[int]
    lane: int
    def __init__(self, lane: _Optional[int] = ...) -> None: ...

class CalibrationData(_message.Message):
    __slots__ = ("lane", "gain_correction")
    LANE_FIELD_NUMBER: _ClassVar[int]
    GAIN_CORRECTION_FIELD_NUMBER: _ClassVar[int]
    lane: int
    gain_correction: float
    def __init__(self, lane: _Optional[int] = ..., gain_correction: _Optional[float] = ...) -> None: ...

class CalibrateDataCommand(_message.Message):
    __slots__ = ("data",)
    DATA_FIELD_NUMBER: _ClassVar[int]
    data: CalibrationData
    def __init__(self, data: _Optional[_Union[CalibrationData, _Mapping]] = ...) -> None: ...

class ReadTemperatureCommand(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class TemperatureMeasurement(_message.Message):
    __slots__ = ("entity", "temperature")
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_FIELD_NUMBER: _ClassVar[int]
    entity: EntityId
    temperature: Temperature
    def __init__(self, entity: _Optional[_Union[EntityId, _Mapping]] = ..., temperature: _Optional[_Union[Temperature, _Mapping]] = ...) -> None: ...

class TemperatureDataset(_message.Message):
    __slots__ = ("measurements",)
    MEASUREMENTS_FIELD_NUMBER: _ClassVar[int]
    measurements: _containers.RepeatedCompositeFieldContainer[TemperatureMeasurement]
    def __init__(self, measurements: _Optional[_Iterable[_Union[TemperatureMeasurement, _Mapping]]] = ...) -> None: ...

class ReadTemperatureResponse(_message.Message):
    __slots__ = ("dataset",)
    DATASET_FIELD_NUMBER: _ClassVar[int]
    dataset: TemperatureDataset
    def __init__(self, dataset: _Optional[_Union[TemperatureDataset, _Mapping]] = ...) -> None: ...

class GetOverloadStatusCommand(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class OverloadStatus(_message.Message):
    __slots__ = ("global_overload", "elements")
    class Element(_message.Message):
        __slots__ = ("entity", "idx", "overload")
        ENTITY_FIELD_NUMBER: _ClassVar[int]
        IDX_FIELD_NUMBER: _ClassVar[int]
        OVERLOAD_FIELD_NUMBER: _ClassVar[int]
        entity: EntityId
        idx: int
        overload: bool
        def __init__(self, entity: _Optional[_Union[EntityId, _Mapping]] = ..., idx: _Optional[int] = ..., overload: _Optional[bool] = ...) -> None: ...
    GLOBAL_OVERLOAD_FIELD_NUMBER: _ClassVar[int]
    ELEMENTS_FIELD_NUMBER: _ClassVar[int]
    global_overload: bool
    elements: _containers.RepeatedCompositeFieldContainer[OverloadStatus.Element]
    def __init__(self, global_overload: _Optional[bool] = ..., elements: _Optional[_Iterable[_Union[OverloadStatus.Element, _Mapping]]] = ...) -> None: ...

class GetOverloadStatusResponse(_message.Message):
    __slots__ = ("status",)
    STATUS_FIELD_NUMBER: _ClassVar[int]
    status: OverloadStatus
    def __init__(self, status: _Optional[_Union[OverloadStatus, _Mapping]] = ...) -> None: ...

class SuccessMessage(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class DeviceBusyMessage(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ErrorMessage(_message.Message):
    __slots__ = ("code", "description")
    CODE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    code: ErrorCode
    description: str
    def __init__(self, code: _Optional[_Union[ErrorCode, str]] = ..., description: _Optional[str] = ...) -> None: ...

class Envelope(_message.Message):
    __slots__ = ("version", "generic", "message_v1")
    VERSION_FIELD_NUMBER: _ClassVar[int]
    GENERIC_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_V1_FIELD_NUMBER: _ClassVar[int]
    version: Version
    generic: GenericMessage
    message_v1: MessageV1
    def __init__(self, version: _Optional[_Union[Version, _Mapping]] = ..., generic: _Optional[_Union[GenericMessage, _Mapping]] = ..., message_v1: _Optional[_Union[MessageV1, _Mapping]] = ...) -> None: ...

class GenericMessage(_message.Message):
    __slots__ = ("ping_command", "ping_response")
    PING_COMMAND_FIELD_NUMBER: _ClassVar[int]
    PING_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    ping_command: PingCommand
    ping_response: PingResponse
    def __init__(self, ping_command: _Optional[_Union[PingCommand, _Mapping]] = ..., ping_response: _Optional[_Union[PingResponse, _Mapping]] = ...) -> None: ...

class BearerAuth(_message.Message):
    __slots__ = ("token",)
    TOKEN_FIELD_NUMBER: _ClassVar[int]
    token: str
    def __init__(self, token: _Optional[str] = ...) -> None: ...

class AuthRequest(_message.Message):
    __slots__ = ("bearer",)
    BEARER_FIELD_NUMBER: _ClassVar[int]
    bearer: BearerAuth
    def __init__(self, bearer: _Optional[_Union[BearerAuth, _Mapping]] = ...) -> None: ...

class Source(_message.Message):
    __slots__ = ("kind", "text")
    class Kind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        MLIR: _ClassVar[Source.Kind]
        ANA: _ClassVar[Source.Kind]
    MLIR: Source.Kind
    ANA: Source.Kind
    KIND_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    kind: Source.Kind
    text: str
    def __init__(self, kind: _Optional[_Union[Source.Kind, str]] = ..., text: _Optional[str] = ...) -> None: ...

class JitCommand(_message.Message):
    __slots__ = ("source",)
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    source: Source
    def __init__(self, source: _Optional[_Union[Source, _Mapping]] = ...) -> None: ...

class Issue(_message.Message):
    __slots__ = ("kind", "lane", "col", "reason")
    class Kind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        INFO: _ClassVar[Issue.Kind]
        WARNING: _ClassVar[Issue.Kind]
        ERROR: _ClassVar[Issue.Kind]
    INFO: Issue.Kind
    WARNING: Issue.Kind
    ERROR: Issue.Kind
    KIND_FIELD_NUMBER: _ClassVar[int]
    LANE_FIELD_NUMBER: _ClassVar[int]
    COL_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    kind: Issue.Kind
    lane: int
    col: int
    reason: str
    def __init__(self, kind: _Optional[_Union[Issue.Kind, str]] = ..., lane: _Optional[int] = ..., col: _Optional[int] = ..., reason: _Optional[str] = ...) -> None: ...

class Diagnosis(_message.Message):
    __slots__ = ("issues",)
    ISSUES_FIELD_NUMBER: _ClassVar[int]
    issues: _containers.RepeatedCompositeFieldContainer[Issue]
    def __init__(self, issues: _Optional[_Iterable[_Union[Issue, _Mapping]]] = ...) -> None: ...

class JitResponse(_message.Message):
    __slots__ = ("success", "diag")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    DIAG_FIELD_NUMBER: _ClassVar[int]
    success: bool
    diag: Diagnosis
    def __init__(self, success: _Optional[bool] = ..., diag: _Optional[_Union[Diagnosis, _Mapping]] = ...) -> None: ...

class UpdateCommand(_message.Message):
    __slots__ = ("begin", "write", "commit", "abort")
    BEGIN_FIELD_NUMBER: _ClassVar[int]
    WRITE_FIELD_NUMBER: _ClassVar[int]
    COMMIT_FIELD_NUMBER: _ClassVar[int]
    ABORT_FIELD_NUMBER: _ClassVar[int]
    begin: UpdateBegin
    write: UpdateWrite
    commit: UpdateCommit
    abort: UpdateAbort
    def __init__(self, begin: _Optional[_Union[UpdateBegin, _Mapping]] = ..., write: _Optional[_Union[UpdateWrite, _Mapping]] = ..., commit: _Optional[_Union[UpdateCommit, _Mapping]] = ..., abort: _Optional[_Union[UpdateAbort, _Mapping]] = ...) -> None: ...

class UpdateResponse(_message.Message):
    __slots__ = ("ack", "failure", "success")
    ACK_FIELD_NUMBER: _ClassVar[int]
    FAILURE_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ack: UpdateAck
    failure: UpdateFailure
    success: UpdateSuccess
    def __init__(self, ack: _Optional[_Union[UpdateAck, _Mapping]] = ..., failure: _Optional[_Union[UpdateFailure, _Mapping]] = ..., success: _Optional[_Union[UpdateSuccess, _Mapping]] = ...) -> None: ...

class UpdateBegin(_message.Message):
    __slots__ = ("size", "hash")
    SIZE_FIELD_NUMBER: _ClassVar[int]
    HASH_FIELD_NUMBER: _ClassVar[int]
    size: int
    hash: bytes
    def __init__(self, size: _Optional[int] = ..., hash: _Optional[bytes] = ...) -> None: ...

class UpdateWrite(_message.Message):
    __slots__ = ("data", "offset")
    DATA_FIELD_NUMBER: _ClassVar[int]
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    data: bytes
    offset: int
    def __init__(self, data: _Optional[bytes] = ..., offset: _Optional[int] = ...) -> None: ...

class UpdateCommit(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class UpdateAbort(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class UpdateAck(_message.Message):
    __slots__ = ("chunk_size",)
    CHUNK_SIZE_FIELD_NUMBER: _ClassVar[int]
    chunk_size: int
    def __init__(self, chunk_size: _Optional[int] = ...) -> None: ...

class UpdateFailure(_message.Message):
    __slots__ = ("reason",)
    REASON_FIELD_NUMBER: _ClassVar[int]
    reason: str
    def __init__(self, reason: _Optional[str] = ...) -> None: ...

class UpdateSuccess(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class MessageV1(_message.Message):
    __slots__ = ("id", "success_message", "error_message", "stand_by_command", "reset_command", "extract_command", "config_command", "start_run_command", "stop_run_command", "manual_control_command", "register_external_entities_command", "get_system_ident_command", "syslog_command", "system_stats_command", "read_system_ident_command", "reset_system_ident_command", "write_system_ident_command", "udp_data_streaming_command", "read_temperature_command", "get_overload_status_command", "calibration_command", "update_command", "extract_response", "config_response", "reset_response", "start_run_response", "run_state_change_message", "run_data_message", "run_data_end_message", "get_system_ident_response", "syslog_response", "system_stats_response", "read_system_ident_response", "reset_system_ident_response", "write_system_ident_response", "read_temperature_response", "get_overload_status_response", "udp_data_streaming_refused_response", "calibration_response", "update_response", "calibrate_init_command", "calibrate_lane_command", "calibrate_offset_command", "calibrate_finalize_command", "calibrate_data_command", "auth_request", "busy_response", "ping_command", "jit_command", "jit_response")
    ID_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    STAND_BY_COMMAND_FIELD_NUMBER: _ClassVar[int]
    RESET_COMMAND_FIELD_NUMBER: _ClassVar[int]
    EXTRACT_COMMAND_FIELD_NUMBER: _ClassVar[int]
    CONFIG_COMMAND_FIELD_NUMBER: _ClassVar[int]
    START_RUN_COMMAND_FIELD_NUMBER: _ClassVar[int]
    STOP_RUN_COMMAND_FIELD_NUMBER: _ClassVar[int]
    MANUAL_CONTROL_COMMAND_FIELD_NUMBER: _ClassVar[int]
    REGISTER_EXTERNAL_ENTITIES_COMMAND_FIELD_NUMBER: _ClassVar[int]
    GET_SYSTEM_IDENT_COMMAND_FIELD_NUMBER: _ClassVar[int]
    SYSLOG_COMMAND_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_STATS_COMMAND_FIELD_NUMBER: _ClassVar[int]
    READ_SYSTEM_IDENT_COMMAND_FIELD_NUMBER: _ClassVar[int]
    RESET_SYSTEM_IDENT_COMMAND_FIELD_NUMBER: _ClassVar[int]
    WRITE_SYSTEM_IDENT_COMMAND_FIELD_NUMBER: _ClassVar[int]
    UDP_DATA_STREAMING_COMMAND_FIELD_NUMBER: _ClassVar[int]
    READ_TEMPERATURE_COMMAND_FIELD_NUMBER: _ClassVar[int]
    GET_OVERLOAD_STATUS_COMMAND_FIELD_NUMBER: _ClassVar[int]
    CALIBRATION_COMMAND_FIELD_NUMBER: _ClassVar[int]
    UPDATE_COMMAND_FIELD_NUMBER: _ClassVar[int]
    EXTRACT_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    CONFIG_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    RESET_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    START_RUN_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    RUN_DATA_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    RUN_DATA_END_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    GET_SYSTEM_IDENT_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    SYSLOG_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_STATS_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    READ_SYSTEM_IDENT_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    RESET_SYSTEM_IDENT_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    WRITE_SYSTEM_IDENT_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    READ_TEMPERATURE_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    GET_OVERLOAD_STATUS_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    UDP_DATA_STREAMING_REFUSED_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    CALIBRATION_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    UPDATE_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    CALIBRATE_INIT_COMMAND_FIELD_NUMBER: _ClassVar[int]
    CALIBRATE_LANE_COMMAND_FIELD_NUMBER: _ClassVar[int]
    CALIBRATE_OFFSET_COMMAND_FIELD_NUMBER: _ClassVar[int]
    CALIBRATE_FINALIZE_COMMAND_FIELD_NUMBER: _ClassVar[int]
    CALIBRATE_DATA_COMMAND_FIELD_NUMBER: _ClassVar[int]
    AUTH_REQUEST_FIELD_NUMBER: _ClassVar[int]
    BUSY_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    PING_COMMAND_FIELD_NUMBER: _ClassVar[int]
    JIT_COMMAND_FIELD_NUMBER: _ClassVar[int]
    JIT_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    id: str
    success_message: SuccessMessage
    error_message: ErrorMessage
    stand_by_command: StandByCommand
    reset_command: ResetCommand
    extract_command: ExtractCommand
    config_command: ConfigCommand
    start_run_command: StartRunCommand
    stop_run_command: StopRunCommand
    manual_control_command: ManualControlCommand
    register_external_entities_command: RegisterExternalEntitiesCommand
    get_system_ident_command: GetSystemIdentCommand
    syslog_command: SyslogCommand
    system_stats_command: SystemStatsCommand
    read_system_ident_command: ReadSystemIdentCommand
    reset_system_ident_command: ResetSystemIdentCommand
    write_system_ident_command: WriteSystemIdentCommand
    udp_data_streaming_command: UdpDataStreamingCommand
    read_temperature_command: ReadTemperatureCommand
    get_overload_status_command: GetOverloadStatusCommand
    calibration_command: CalibrationCommand
    update_command: UpdateCommand
    extract_response: ExtractResponse
    config_response: ConfigResponse
    reset_response: ResetResponse
    start_run_response: StartRunResponse
    run_state_change_message: RunStateChangeMessage
    run_data_message: RunDataMessage
    run_data_end_message: RunDataEndMessage
    get_system_ident_response: GetSystemIdentResponse
    syslog_response: SyslogResponse
    system_stats_response: SystemStatsResponse
    read_system_ident_response: ReadSystemIdentResponse
    reset_system_ident_response: ResetSystemIdentResponse
    write_system_ident_response: WriteSystemIdentResponse
    read_temperature_response: ReadTemperatureResponse
    get_overload_status_response: GetOverloadStatusResponse
    udp_data_streaming_refused_response: UdpDataStreamingRefusedResponse
    calibration_response: CalibrationResponse
    update_response: UpdateResponse
    calibrate_init_command: CalibrateInitCommand
    calibrate_lane_command: CalibrateLaneCommand
    calibrate_offset_command: CalibrateOffsetCommand
    calibrate_finalize_command: CalibrateFinalizeCommand
    calibrate_data_command: CalibrateDataCommand
    auth_request: AuthRequest
    busy_response: DeviceBusyMessage
    ping_command: PingCommand
    jit_command: JitCommand
    jit_response: JitResponse
    def __init__(self, id: _Optional[str] = ..., success_message: _Optional[_Union[SuccessMessage, _Mapping]] = ..., error_message: _Optional[_Union[ErrorMessage, _Mapping]] = ..., stand_by_command: _Optional[_Union[StandByCommand, _Mapping]] = ..., reset_command: _Optional[_Union[ResetCommand, _Mapping]] = ..., extract_command: _Optional[_Union[ExtractCommand, _Mapping]] = ..., config_command: _Optional[_Union[ConfigCommand, _Mapping]] = ..., start_run_command: _Optional[_Union[StartRunCommand, _Mapping]] = ..., stop_run_command: _Optional[_Union[StopRunCommand, _Mapping]] = ..., manual_control_command: _Optional[_Union[ManualControlCommand, _Mapping]] = ..., register_external_entities_command: _Optional[_Union[RegisterExternalEntitiesCommand, _Mapping]] = ..., get_system_ident_command: _Optional[_Union[GetSystemIdentCommand, _Mapping]] = ..., syslog_command: _Optional[_Union[SyslogCommand, _Mapping]] = ..., system_stats_command: _Optional[_Union[SystemStatsCommand, _Mapping]] = ..., read_system_ident_command: _Optional[_Union[ReadSystemIdentCommand, _Mapping]] = ..., reset_system_ident_command: _Optional[_Union[ResetSystemIdentCommand, _Mapping]] = ..., write_system_ident_command: _Optional[_Union[WriteSystemIdentCommand, _Mapping]] = ..., udp_data_streaming_command: _Optional[_Union[UdpDataStreamingCommand, _Mapping]] = ..., read_temperature_command: _Optional[_Union[ReadTemperatureCommand, _Mapping]] = ..., get_overload_status_command: _Optional[_Union[GetOverloadStatusCommand, _Mapping]] = ..., calibration_command: _Optional[_Union[CalibrationCommand, _Mapping]] = ..., update_command: _Optional[_Union[UpdateCommand, _Mapping]] = ..., extract_response: _Optional[_Union[ExtractResponse, _Mapping]] = ..., config_response: _Optional[_Union[ConfigResponse, _Mapping]] = ..., reset_response: _Optional[_Union[ResetResponse, _Mapping]] = ..., start_run_response: _Optional[_Union[StartRunResponse, _Mapping]] = ..., run_state_change_message: _Optional[_Union[RunStateChangeMessage, _Mapping]] = ..., run_data_message: _Optional[_Union[RunDataMessage, _Mapping]] = ..., run_data_end_message: _Optional[_Union[RunDataEndMessage, _Mapping]] = ..., get_system_ident_response: _Optional[_Union[GetSystemIdentResponse, _Mapping]] = ..., syslog_response: _Optional[_Union[SyslogResponse, _Mapping]] = ..., system_stats_response: _Optional[_Union[SystemStatsResponse, _Mapping]] = ..., read_system_ident_response: _Optional[_Union[ReadSystemIdentResponse, _Mapping]] = ..., reset_system_ident_response: _Optional[_Union[ResetSystemIdentResponse, _Mapping]] = ..., write_system_ident_response: _Optional[_Union[WriteSystemIdentResponse, _Mapping]] = ..., read_temperature_response: _Optional[_Union[ReadTemperatureResponse, _Mapping]] = ..., get_overload_status_response: _Optional[_Union[GetOverloadStatusResponse, _Mapping]] = ..., udp_data_streaming_refused_response: _Optional[_Union[UdpDataStreamingRefusedResponse, _Mapping]] = ..., calibration_response: _Optional[_Union[CalibrationResponse, _Mapping]] = ..., update_response: _Optional[_Union[UpdateResponse, _Mapping]] = ..., calibrate_init_command: _Optional[_Union[CalibrateInitCommand, _Mapping]] = ..., calibrate_lane_command: _Optional[_Union[CalibrateLaneCommand, _Mapping]] = ..., calibrate_offset_command: _Optional[_Union[CalibrateOffsetCommand, _Mapping]] = ..., calibrate_finalize_command: _Optional[_Union[CalibrateFinalizeCommand, _Mapping]] = ..., calibrate_data_command: _Optional[_Union[CalibrateDataCommand, _Mapping]] = ..., auth_request: _Optional[_Union[AuthRequest, _Mapping]] = ..., busy_response: _Optional[_Union[DeviceBusyMessage, _Mapping]] = ..., ping_command: _Optional[_Union[PingCommand, _Mapping]] = ..., jit_command: _Optional[_Union[JitCommand, _Mapping]] = ..., jit_response: _Optional[_Union[JitResponse, _Mapping]] = ...) -> None: ...

class File(_message.Message):
    __slots__ = ("version", "module")
    VERSION_FIELD_NUMBER: _ClassVar[int]
    MODULE_FIELD_NUMBER: _ClassVar[int]
    version: Version
    module: Module
    def __init__(self, version: _Optional[_Union[Version, _Mapping]] = ..., module: _Optional[_Union[Module, _Mapping]] = ...) -> None: ...
