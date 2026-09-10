"""Rutas protegidas para tareas administrativas programadas."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, status

from aplicacion.dependencias import SesionActual
from aplicacion.errores import ErrorConfirmacionRequerida
from aplicacion.esquemas.tareas import (
    CancelarTareaProgramada,
    CrearTareaProgramada,
    EjecucionTareaRespuesta,
    TareaProgramadaRespuesta,
)
from aplicacion.modelos.acceso import Usuario
from aplicacion.modelos.enumeraciones import EstadoTareaProgramada
from aplicacion.seguridad.autenticacion import exigir_permiso
from aplicacion.servicios.gestor_tareas import (
    cancelar_tarea_programada,
    crear_tarea_programada,
    listar_ejecuciones_tarea,
    listar_tareas_programadas,
    obtener_tarea_programada,
)

enrutador = APIRouter(prefix="/api/v1/tareas", tags=["tareas"])
UsuarioConsultaTareas = Annotated[Usuario, Depends(exigir_permiso("consultar_tareas"))]
UsuarioGestionTareas = Annotated[Usuario, Depends(exigir_permiso("gestionar_tareas"))]
IdentificadorTarea = Annotated[int, Path(gt=0)]


@enrutador.post(
    "",
    response_model=TareaProgramadaRespuesta,
    status_code=status.HTTP_201_CREATED,
)
async def crear_tarea(
    datos: CrearTareaProgramada,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioGestionTareas,
) -> TareaProgramadaRespuesta:
    """Programa una acción ya autorizada sobre destinos congelados."""

    return await crear_tarea_programada(
        sesion,
        datos,
        usuario,
        solicitud,
        solicitud.app.state.configuracion,
    )


@enrutador.get("", response_model=list[TareaProgramadaRespuesta])
async def consultar_tareas(
    sesion: SesionActual,
    _: UsuarioConsultaTareas,
    estado: Annotated[EstadoTareaProgramada | None, Query()] = None,
    desplazamiento: Annotated[int, Query(ge=0)] = 0,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[TareaProgramadaRespuesta]:
    return await listar_tareas_programadas(
        sesion,
        estado=estado,
        desplazamiento=desplazamiento,
        limite=limite,
    )


@enrutador.get("/{id_tarea_programada}", response_model=TareaProgramadaRespuesta)
async def consultar_tarea(
    id_tarea_programada: IdentificadorTarea,
    sesion: SesionActual,
    _: UsuarioConsultaTareas,
) -> TareaProgramadaRespuesta:
    return await obtener_tarea_programada(sesion, id_tarea_programada)


@enrutador.get(
    "/{id_tarea_programada}/ejecuciones",
    response_model=list[EjecucionTareaRespuesta],
)
async def consultar_ejecuciones(
    id_tarea_programada: IdentificadorTarea,
    sesion: SesionActual,
    _: UsuarioConsultaTareas,
    desplazamiento: Annotated[int, Query(ge=0)] = 0,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[EjecucionTareaRespuesta]:
    return await listar_ejecuciones_tarea(
        sesion,
        id_tarea_programada,
        desplazamiento=desplazamiento,
        limite=limite,
    )


@enrutador.post(
    "/{id_tarea_programada}/cancelar",
    response_model=TareaProgramadaRespuesta,
)
async def cancelar_tarea(
    id_tarea_programada: IdentificadorTarea,
    datos: CancelarTareaProgramada,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioGestionTareas,
) -> TareaProgramadaRespuesta:
    if not datos.confirmar:
        raise ErrorConfirmacionRequerida()
    return await cancelar_tarea_programada(
        sesion,
        id_tarea_programada,
        usuario,
        solicitud,
    )
