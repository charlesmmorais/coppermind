"""Pure operations on the board model.

These functions mutate a Board in place. They enforce only *cheap, local*
invariants (e.g. duplicate reference). Structural and design-rule checking lives
in the verification layer and runs at commit time. Operations never touch KiCAD.
"""

from __future__ import annotations

from coppermind.domain.models import (
    Board,
    BoardOutline,
    Component,
    Layer,
    Net,
    Point,
    Track,
    Via,
)


def create_board(name: str, width: float, height: float) -> Board:
    return Board(name=name, outline=BoardOutline(width=width, height=height))


def add_component(
    board: Board,
    reference: str,
    footprint: str,
    x: float,
    y: float,
    value: str = "",
    rotation: float = 0.0,
    layer: Layer = Layer.F_CU,
) -> Component:
    if reference in board.components:
        raise ValueError(f"component '{reference}' already exists")
    comp = Component(
        reference=reference,
        footprint=footprint,
        value=value,
        position=Point(x=x, y=y),
        rotation=rotation,
        layer=layer,
    )
    board.components[reference] = comp
    return comp


def move_component(board: Board, reference: str, x: float, y: float) -> Component:
    if reference not in board.components:
        raise ValueError(f"component '{reference}' does not exist")
    comp = board.components[reference]
    moved = comp.model_copy(update={"position": Point(x=x, y=y)})
    board.components[reference] = moved
    return moved


def create_net(board: Board, name: str) -> Net:
    if name in board.nets:
        raise ValueError(f"net '{name}' already exists")
    net = Net(name=name)
    board.nets[name] = net
    return net


def route_track(
    board: Board,
    net: str,
    start: tuple[float, float],
    end: tuple[float, float],
    width: float = 0.25,
    layer: Layer = Layer.F_CU,
) -> Track:
    track = Track(
        net=net,
        start=Point(x=start[0], y=start[1]),
        end=Point(x=end[0], y=end[1]),
        width=width,
        layer=layer,
    )
    board.tracks.append(track)
    return track


def delete_component(board: Board, reference: str) -> None:
    if reference not in board.components:
        raise ValueError(f"component '{reference}' does not exist")
    del board.components[reference]


def edit_component(board: Board, reference: str, *, value: str | None = None,
                   footprint: str | None = None, rotation: float | None = None) -> Component:
    if reference not in board.components:
        raise ValueError(f"component '{reference}' does not exist")
    comp = board.components[reference]
    updates: dict[str, object] = {}
    if value is not None:
        updates["value"] = value
    if footprint is not None:
        updates["footprint"] = footprint
    if rotation is not None:
        updates["rotation"] = rotation
    edited = comp.model_copy(update=updates)
    board.components[reference] = edited
    return edited


def add_via(
    board: Board,
    x: float,
    y: float,
    net: str = "",
    diameter: float = 0.8,
    drill: float = 0.4,
) -> Via:
    via = Via(position=Point(x=x, y=y), net=net, diameter=diameter, drill=drill)
    board.vias.append(via)
    return via
