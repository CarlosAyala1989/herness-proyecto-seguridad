"""Rutas HTTP protegidas para configuración y transferencia de archivos."""

import re
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from aplicacion.dependencias import SesionActual
from aplicacion.errores import ErrorConfirmacionRequerida, ErrorLimiteArchivoExcedido
from aplicacion.esquemas.archivos import (
    CargaArchivoRespuesta,
    CrearRutaArchivoPermitida,
    InformacionArchivoRespuesta,
    RutaArchivoPermitidaDetalle,
)
from aplicacion.modelos.acceso import Usuario
from aplicacion.seguridad.autenticacion import exigir_permiso
from aplicacion.servicios import gestor_archivos

enrutador = APIRouter(prefix="/api/v1/servidores/{id_servidor}", tags=["archivos"])
IdentificadorServidor = Annotated[int, Path(gt=0)]
IdentificadorRuta = Annotated[int, Path(gt=0)]
RutaRemota = Annotated[str, Query(min_length=2, max_length=1024)]
UsuarioConsulta = Annotated[Usuario, Depends(exigir_permiso("consultar_archivos"))]
UsuarioDescarga = Annotated[Usuario, Depends(exigir_permiso("descargar_archivos"))]
UsuarioCarga = Annotated[Usuario, Depends(exigir_permiso("cargar_archivos"))]
UsuarioGestion = Annotated[Usuario, Depends(exigir_permiso("gestionar_rutas_archivos"))]


@enrutador.get(
    "/rutas-archivos-permitidas",
    response_model=list[RutaArchivoPermitidaDetalle],
)
async def consultar_rutas_archivos(
    id_servidor: IdentificadorServidor,
    sesion: SesionActual,
    _: UsuarioConsulta,
) -> list[RutaArchivoPermitidaDetalle]:
    rutas = await gestor_archivos.listar_rutas_archivos(sesion, id_servidor)
    return [RutaArchivoPermitidaDetalle.model_validate(item) for item in rutas]


@enrutador.post(
    "/rutas-archivos-permitidas",
    response_model=RutaArchivoPermitidaDetalle,
    status_code=status.HTTP_201_CREATED,
)
async def registrar_ruta_archivo(
    id_servidor: IdentificadorServidor,
    datos: CrearRutaArchivoPermitida,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioGestion,
) -> RutaArchivoPermitidaDetalle:
    entidad = await gestor_archivos.crear_ruta_archivo(
        sesion, id_servidor, datos, usuario, solicitud
    )
    return RutaArchivoPermitidaDetalle.model_validate(entidad)


@enrutador.delete(
    "/rutas-archivos-permitidas/{id_ruta}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def borrar_ruta_archivo(
    id_servidor: IdentificadorServidor,
    id_ruta: IdentificadorRuta,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioGestion,
    confirmar: Annotated[bool, Query()] = False,
) -> Response:
    if not confirmar:
        raise ErrorConfirmacionRequerida()
    await gestor_archivos.eliminar_ruta_archivo(sesion, id_servidor, id_ruta, usuario, solicitud)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@enrutador.get("/archivos/informacion", response_model=InformacionArchivoRespuesta)
async def consultar_informacion(
    id_servidor: IdentificadorServidor,
    ruta_remota: RutaRemota,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioConsulta,
) -> InformacionArchivoRespuesta:
    return await gestor_archivos.consultar_informacion_archivo(
        sesion,
        id_servidor,
        ruta_remota,
        usuario,
        solicitud.app.state.fabrica_transporte_remoto,
        solicitud.app.state.configuracion,
        solicitud,
    )


@enrutador.get("/archivos/descargar")
async def obtener_archivo(
    id_servidor: IdentificadorServidor,
    ruta_remota: RutaRemota,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioDescarga,
) -> Response:
    descarga = await gestor_archivos.descargar_archivo(
        sesion,
        id_servidor,
        ruta_remota,
        usuario,
        solicitud.app.state.fabrica_transporte_remoto,
        solicitud.app.state.configuracion,
        solicitud,
    )
    nombre_ascii = re.sub(r"[^A-Za-z0-9._-]", "_", descarga.nombre_archivo) or "archivo"
    nombre_utf8 = quote(descarga.nombre_archivo, safe="")
    return Response(
        content=descarga.contenido,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{nombre_ascii}\"; filename*=UTF-8''{nombre_utf8}"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@enrutador.put("/archivos/cargar", response_model=CargaArchivoRespuesta)
async def enviar_archivo(
    id_servidor: IdentificadorServidor,
    ruta_remota: RutaRemota,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioCarga,
    sobrescribir: Annotated[bool, Query()] = False,
    confirmar: Annotated[bool, Query()] = False,
) -> CargaArchivoRespuesta:
    if sobrescribir and not confirmar:
        raise ErrorConfirmacionRequerida()
    limite = solicitud.app.state.configuracion.limite_archivo_transferencia_bytes
    longitud = solicitud.headers.get("content-length")
    if longitud is not None:
        try:
            longitud_entera = int(longitud)
        except ValueError:
            await gestor_archivos.auditar_carga_rechazada_por_tamano(
                sesion, id_servidor, usuario, solicitud
            )
            raise ErrorLimiteArchivoExcedido(limite) from None
        if longitud_entera < 0 or longitud_entera > limite:
            await gestor_archivos.auditar_carga_rechazada_por_tamano(
                sesion, id_servidor, usuario, solicitud
            )
            raise ErrorLimiteArchivoExcedido(limite)
    contenido = bytearray()
    async for bloque in solicitud.stream():
        contenido.extend(bloque)
        if len(contenido) > limite:
            await gestor_archivos.auditar_carga_rechazada_por_tamano(
                sesion, id_servidor, usuario, solicitud
            )
            raise ErrorLimiteArchivoExcedido(limite)
    return await gestor_archivos.cargar_archivo(
        sesion,
        id_servidor,
        ruta_remota,
        bytes(contenido),
        sobrescribir,
        usuario,
        solicitud.app.state.fabrica_transporte_remoto,
        solicitud.app.state.configuracion,
        solicitud,
    )
