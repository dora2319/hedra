from enum import Enum


class PluginHooks(Enum):
    ON_ENGINE_CONNECT='ON_ENGINE_CONNECT'
    ON_ENGINE_EXECUTE='ON_ENGINE_EXECUTE'
    ON_ENGINE_CLOSE='ON_ENGINE_CLOSE'
    ON_PERSONA_SETUP='ON_PERSONA_SETUP'
    ON_PERSONA_GENERATE='ON_PERSONA_GENERATE'
    ON_PERSONA_SHUTDOWN='ON_PERSONA_SHUTDOWN'
    ON_REPORTER_CONNECT='ON_REPORTER_CONNECT'
    ON_REPORTER_CLOSE='ON_REPORTER_CLOSE'
    ON_PROCESS_EVENTS='ON_PROCESS_EVENTS'
    ON_PROCESS_SHARED_STATS='ON_PROCESS_SHARED_STATS'
    ON_PROCESS_METRICS='ON_PROCESS_METRICS'
    ON_PROCESS_CUSTOM_STATS='ON_PROCESS_CUSTOM_STATS'
    ON_PROCESS_ERRORS='ON_PROCESS_ERRORS'
    CUSTOM='CUSTOM'