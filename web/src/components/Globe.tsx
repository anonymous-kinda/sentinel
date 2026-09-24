import { useEffect, useRef } from "react";
import {
  ArcType,
  buildModuleUrl,
  Cartesian2,
  Cartesian3,
  Color,
  HeadingPitchRange,
  ImageryLayer,
  LabelStyle,
  TileMapServiceImageryProvider,
  HorizontalOrigin,
  VerticalOrigin,
  Viewer,
  BoundingSphere,
  Entity,
} from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import type { Trajectory } from "../api/types";

export interface GlobeMarker {
  id: string;
  lat: number;
  lon: number;
  label: string;
  color: string;
}

/**
 * CesiumJS globe - the same engine as Wayfinder - configured to make no
 * network requests beyond this node: imagery is the NaturalEarthII tile
 * set bundled with Cesium, there is no ion token, no geocoder and no
 * terrain server. It works on a disconnected network or it is not a field
 * tool.
 */
export function Globe({
  trajectory,
  primaryName,
  secondaryName,
  markers = [],
}: {
  trajectory: Trajectory | null;
  primaryName?: string;
  secondaryName?: string;
  markers?: GlobeMarker[];
}) {
  const container = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);
  const entities = useRef<Entity[]>([]);
  const markerEntities = useRef<Entity[]>([]);

  useEffect(() => {
    if (!container.current) return;
    const v = new Viewer(container.current, {
      baseLayer: ImageryLayer.fromProviderAsync(
        TileMapServiceImageryProvider.fromUrl(buildModuleUrl("Assets/Textures/NaturalEarthII")),
        {},
      ),
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      animation: false,
      timeline: false,
      fullscreenButton: false,
      infoBox: false,
      selectionIndicator: false,
      creditContainer: document.createElement("div"),
    });
    v.scene.globe.enableLighting = false;
    v.scene.backgroundColor = Color.fromCssColorString("#070b10");
    v.scene.globe.baseColor = Color.fromCssColorString("#0d1620");
    if (v.scene.skyAtmosphere) v.scene.skyAtmosphere.show = true;
    viewer.current = v;
    return () => {
      v.destroy();
      viewer.current = null;
    };
  }, []);

  useEffect(() => {
    const v = viewer.current;
    if (!v) return;
    entities.current.forEach((e) => v.entities.remove(e));
    entities.current = [];
    if (!trajectory) return;

    const toCart = (s: [number, number, number, number]) => new Cartesian3(s[1], s[2], s[3]);
    const draw = (samples: Trajectory["primary"], color: Color, name: string, side: 1 | -1) => {
      const positions = samples.map(toCart);
      const tcaIndex = samples.findIndex((s) => s[0] === 0);
      const at = positions[tcaIndex >= 0 ? tcaIndex : Math.floor(positions.length / 2)];
      entities.current.push(
        v.entities.add({
          polyline: { positions, width: 2.2, material: color, arcType: ArcType.NONE },
        }),
        v.entities.add({
          position: at,
          point: { pixelSize: 9, color, outlineColor: Color.BLACK, outlineWidth: 1 },
          label: {
            text: name,
            font: "12px ui-monospace, monospace",
            fillColor: color,
            style: LabelStyle.FILL_AND_OUTLINE,
            outlineWidth: 3,
            outlineColor: Color.BLACK,
            // The two objects meet at TCA: put one label above-left and the
            // other below-right so they never overprint.
            verticalOrigin: side > 0 ? VerticalOrigin.BOTTOM : VerticalOrigin.TOP,
            horizontalOrigin: side > 0 ? HorizontalOrigin.RIGHT : HorizontalOrigin.LEFT,
            pixelOffset: new Cartesian2(-10 * side, -10 * side),
          },
        }),
      );
      return positions;
    };
    const p = draw(trajectory.primary, Color.fromCssColorString("#5ad1ff"), primaryName ?? "primary", 1);
    draw(trajectory.secondary, Color.fromCssColorString("#ffb347"), secondaryName ?? "secondary", -1);

    const center = p[Math.floor(p.length / 2)];
    const sphere = new BoundingSphere(center, 1);
    v.camera.flyToBoundingSphere(sphere, {
      duration: 1.2,
      offset: new HeadingPitchRange(0.0, -0.9, 9_000_000),
    });
  }, [trajectory, primaryName, secondaryName]);

  useEffect(() => {
    const v = viewer.current;
    if (!v) return;
    markerEntities.current.forEach((e) => v.entities.remove(e));
    markerEntities.current = markers.map((m) =>
      v.entities.add({
        position: Cartesian3.fromDegrees(m.lon, m.lat, 0),
        point: { pixelSize: 11, color: Color.fromCssColorString(m.color), outlineColor: Color.BLACK, outlineWidth: 2 },
        label: {
          text: m.label,
          font: "12px ui-monospace, monospace",
          fillColor: Color.fromCssColorString(m.color),
          style: LabelStyle.FILL_AND_OUTLINE,
          outlineWidth: 3,
          outlineColor: Color.BLACK,
          verticalOrigin: VerticalOrigin.BOTTOM,
          pixelOffset: new Cartesian2(0, -14),
        },
      }),
    );
  }, [markers]);

  return <div className="globe" ref={container} />;
}
