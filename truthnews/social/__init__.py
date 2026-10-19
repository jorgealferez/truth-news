"""Autopublicacion en redes (Fase 4, ADR 0018): seleccion, piezas por red, adaptadores y cola.

El worker llama a `queue.run` en cada ciclo. Sin credenciales de una red, sus piezas se generan y se
registran en `social_post` con estado `prueba`, pero no se envian.
"""
