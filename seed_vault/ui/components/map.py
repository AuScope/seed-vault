import streamlit as st
from typing import List, Dict, Union
from obspy.geodetics.base import degrees2kilometers
import folium
from folium.plugins import Draw, Fullscreen
from folium import MacroElement
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import time
import numpy as np
import pandas as pd
import jinja2

from seed_vault.models.common import RectangleArea, CircleArea 
from seed_vault.enums.ui import Steps
from seed_vault.utils.constants import AREA_COLOR
from seed_vault.models.config import GeometryConstraint



DEFAULT_COLOR_MARKER = 'blue'

icon = folium.DivIcon(html="""
    <svg width="20" height="20" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
      <polygon points="50,15 90,85 10,85" style="fill:blue;stroke:black;stroke-width:2" />
    </svg>
""")


def create_map(map_center=[0.0, 0.0], zoom_start=2, map_id=None):
    """
    Create a base map with controls but without dynamic layers.
    """
    m = folium.Map(
        location=map_center,
        zoom_start=zoom_start,
        id=map_id,
    )

    folium.TileLayer(
        tiles='CartoDB positron',  
        attr='Map data © OpenStreetMap contributors, CartoDB',
        name='Mirrored Layer',
        control=False,
        no_wrap=False,
        bounds = [[-90, -180], [90, 180]]
    ).add_to(m)

    # Add the main tile layer (blue) with no_wrap enabled
    folium.TileLayer(
        tiles='OpenStreetMap',
        name='Main Layer',
        control=False,
        no_wrap=True ,
        bounds = [[-90, -180], [90, 180]]
    ).add_to(m)
    
    # m.location = [0, 0]


    add_draw_controls(m)
    add_fullscreen_control(m)
    return m

def add_draw_controls(map_object):
    """
    Add draw controls to the map.
    """
    Draw(
        draw_options={
            'polyline': False,
            'rectangle': True,
            'polygon': False,
            'circle': True,
            'marker': False,
            'circlemarker': False,
        },
        edit_options={
            'edit': False,
            'remove': False  
        },
        export=False
    ).add_to(map_object)

def add_fullscreen_control(map_object):
    """
    Add fullscreen control to the map.
    """
    Fullscreen(
        position="topright",
        title="Expand me",
        title_cancel="Exit me",
        force_separate_button=True,
    ).add_to(map_object)

def add_area_overlays(areas):
    """
    Add overlays representing areas (Rectangles or Circles) to the map.
    """
    feature_group = folium.FeatureGroup(name="Areas")
    for area in areas:
        coords = area.coords
        if isinstance(coords, RectangleArea):
            feature_group.add_child(folium.Rectangle(
                bounds=[[coords.min_lat, coords.min_lng], [coords.max_lat, coords.max_lng]],
                color=coords.color,
                fill=True,
                fill_opacity=0.5
            ))
        elif isinstance(coords, CircleArea):
            add_circle_area(feature_group, coords)
    
    return feature_group
        
def add_circle_area(feature_group, coords):
    """
    Add circle area (inner and outer) to the feature group.
    """
    if coords.min_radius == 0:
        feature_group.add_child(folium.Circle(
            location=[coords.lat, coords.lng],
            radius=degrees2kilometers(coords.max_radius)*1000,
            color= AREA_COLOR,
            fill=True,
            fill_opacity=0.5
        ))
    else:
        # Outer Circle
        feature_group.add_child(folium.Circle(
            location=[coords.lat, coords.lng],
            radius=degrees2kilometers(coords.max_radius)*1000,
            color=coords.color,
            fill=False,
            dash_array='2, 4',
            weight=2,
        ))
        # Inner Circle
        feature_group.add_child(folium.Circle(
            location=[coords.lat, coords.lng],
            radius=degrees2kilometers(coords.max_radius)*1000,
            color=coords.color,
            fill=False,
            dash_array='2, 4',
            weight=2,
        ))


def add_data_points(df, cols_to_disp, step: Steps, selected_idx=[], col_color=None, col_size=None):
    """
    Add points to map
    """
    fg = folium.FeatureGroup(name="Marker " + step.value)

    marker_info = {}

    # Handling the color map
    fig = None
    if col_color is not None:

        # Create legend with continuous colour range
        if pd.api.types.is_numeric_dtype(df[col_color]):
            fig, ax = plt.subplots(figsize=(1, 22))
            # norm = mcolors.Normalize(vmin=df[col_color].min(), vmax=df[col_color].max())
            norm = mcolors.Normalize(vmin=-5, vmax=500)
            colormap = cm.get_cmap('inferno_r')

            fig.subplots_adjust(bottom=0.5)
            colorbar = fig.colorbar(cm.ScalarMappable(norm=norm, cmap=colormap), cax=ax, orientation='vertical')
            colorbar.set_label(f'Color range for {col_color}', fontsize=16)
            colorbar.ax.tick_params(labelsize=14)

        else:
            # Create legend with discrete color range
            max_display_categories = 15 # Max number of categories in legend

            unique_categories = df[col_color].unique()

            # If too many categories then truncate
            if len(unique_categories) > max_display_categories:
                display_cats = unique_categories[:max_display_categories]
                display_cats = np.append(display_cats, "...")
            else:
                display_cats = unique_categories

            # Create a colour map using 'display_cats'
            colors = cm.get_cmap('tab10', len(display_cats))
            legend_category_color_map = {category: mcolors.rgb2hex(colors(i)[:3]) for i, category in enumerate(display_cats)}

            # Create legend
            fig, ax = plt.subplots(figsize=(2, len(display_cats) * 0.5))
            ax.axis('off')  # Hide the axis for categories
            legend_labels = [plt.Line2D([0], [0], color=color, lw=4) for color in legend_category_color_map.values()]
            legend = ax.legend(legend_labels, legend_category_color_map.keys(), loc='center', ncol=1, fontsize=24)

            # Create a colour map for the geospatial map which has all unique categories
            category_color_map = {category: mcolors.rgb2hex(colors(i)[:3]) for i, category in enumerate(unique_categories)}

    # Loop to create all the map markers
    for index, row in df.iterrows():
        # Determine color
        if col_color is None:
            color = DEFAULT_COLOR_MARKER
        elif pd.api.types.is_numeric_dtype(df[col_color]):
            color = mcolors.rgb2hex(colormap(norm(row[col_color]))[:3])
        else:
            color = category_color_map[row[col_color]]

        # Determine marker size
        size = 5
        if col_size is None:
            size = 6
        else:
            if col_size == "magnitude":
                size = get_marker_size(row[col_size])
            else:
                size = 2 + (10 * (row[col_size]) / (9))
            size = np.clip(size, 5, 15)

        if index in selected_idx:
            size = 1.2 *size

        # Determine edge color and fill opacity for selected markers
        edge_color = 'black' if index in selected_idx else color
        # size = 7 if index in selected_idx else size
        fill_opacity = 1.0 if index in selected_idx else 0.2

        # Create popup content
        popup_content = create_popup(index, row, cols_to_disp, step)
        popup = folium.Popup(html=popup_content, max_width=2650, min_width=200)

        tooltip_text = create_popup(index, row, cols_to_disp, step, truncate=True)

        # Add marker to the cluster
        latitude, longitude = row['latitude'], row['longitude']
        add_marker_to_cluster(fg, latitude, longitude, color, edge_color, size, fill_opacity, popup, tooltip_text, step)

        # Store marker information
        # marker_key = (latitude, longitude)
        marker_key = int(index + 1)
        if marker_key not in marker_info:
            marker_info[marker_key] = {"id": int(index + 1)}

        marker_info[marker_key]['step'] = step.value

        for k, v in cols_to_disp.items():
            marker_info[marker_key][v] = row[k]

    return fg, marker_info, fig



def add_marker_to_cluster(fg, latitude, longitude, color, edge_color, size, fill_opacity, popup, tooltip_text, step):
    """
    Add a marker to a cluster with specific attributes.
    """
    if step == Steps.EVENT:
        fg.add_child (folium.CircleMarker(
                location=[latitude, longitude],
                radius=size,
                popup=popup,
                tooltip=tooltip_text,
                color=edge_color,
                fill=True,
                fill_color=color,
                fill_opacity=fill_opacity,
        ))

    if step == Steps.STATION:
        fg.add_child(folium.RegularPolygonMarker(
            location=[latitude, longitude],
            number_of_sides=3,
            rotation=-90,
            radius=size,
            popup=popup,
            tooltip=tooltip_text,
            color=edge_color,
            fill=True,
            fill_color=color,
            fill_opacity=fill_opacity,
        ))

    # if step == Steps.STATION:
    #     folium.RegularPolygonMarker(
    #         location=[latitude, longitude],
    #         number_of_sides=5,  # Change this for different shapes (3 for triangle, 4 for square, etc.)
    #         rotation=0,
    #         radius=size,
    #         popup=popup,
    #         color=edge_color,
    #         fill=True,
    #         fill_color=color,
    #         fill_opacity=fill_opacity,
    #     ).add_to(fg)
    #     # fg.add_child(folium.Marker(
    #     #     location=[latitude, longitude],
    #     #     icon=icon,
    #     #     popup=popup,
    #     #     # color=edge_color,
    #     #     # fill=True,
    #     #     # fill_color=color,
    #     #     # fill_opacity=fill_opacity,
    #     # ))
                   
def clear_map_layers(map_object):
    """
    Remove all FeatureGroup layers from the map object.
    """
    if map_object is not None:
        try:
            layers_to_remove = [
                key for key, layer in map_object._children.items()
                if isinstance(layer, folium.map.FeatureGroup)
            ]
            for key in layers_to_remove:
                map_object._children.pop(key)
        except Exception as e:
            print(f"Error clearing map layers: {e}")     

#def get_marker_size(magnitude):
#    import math
#    base_size = 2.0
#    scaling_factor = 2.5
#    size = base_size + scaling_factor * math.log(magnitude + 1)
#    return min(13.0, max(base_size, size))

def get_marker_size(magnitude):
    if magnitude < 2:
        return 0.5
    if magnitude < 3:
        return 1.0
    elif magnitude < 4:
        return 1.5
    if magnitude <= 5:
        return 2.0
    elif magnitude >= 8:
        return 14.0
    else:
        x = (magnitude - 5) / 3
        return 2 + 12 * x**2


def get_marker_color(magnitude):
    if magnitude < 1.8:
        return 'silver'
    elif 1.8 <= magnitude < 2.4:
        return 'yellow'
    elif 2.4 <= magnitude < 5:
        return 'orange'
    elif 5 <= magnitude < 7:
        return 'red'
    elif 7 <= magnitude < 8.5:
        return 'magenta'
    else:
        return 'purple'
    

def get_color_map(df, c, offset=0.0, cmap='viridis'):
    """
    offset: 0.0 <= offset <= 1   -> it is used to lower the range of colors
    """
    colormap = cm.get_cmap(cmap) 
    min_val, max_val = [df[c].min(), df[c].max()]
    norm = Normalize(vmin=min_val + offset * min_val, vmax=max_val - offset)

    return norm, colormap
    




def truncate_text(text, max_length=47):
    """Truncate text and add '...' if it exceeds max_length"""
    return text if len(text) <= max_length else text[:max_length] + "..."


def create_popup(index, row, cols_to_disp, step: Steps = None, truncate: bool = False):
    html_disp = ""
    if step == Steps.EVENT:
        html_disp = f"<h4><b>{truncate_text(row['place']) if truncate else row['place']}</b></h4>"
        html_disp += f"<h5>{row['magnitude']:.2f} {row['magnitude type']}</h5>"
        html_disp += f"<h5>{row['time']} (UTC)</h5>"
        html_disp += f"<h5>{row['latitude']:.2f} latitude, {row['longitude']:.2f} longitude, {row['depth (km)']:.2f} km</h5>"
        html_disp += f"<p style='color:black; font-size:2px; opacity:0;'>Event {index + 1}</p>"

    if step == Steps.STATION:
        html_disp = f"<h4><b>{row['network']}.{row['station']}</b></h4>"
        html_disp += f"<h5>{truncate_text(row['description']) if truncate else row['description']}</h5>"
        html_disp += f"<h5>({row['start date (UTC)']} - {row['end date (UTC)']})</h5>"
        html_disp += f"<h5>{truncate_text(row['channels']) if truncate else row['channels']}</h5>"
        html_disp += f"<h5>{row['latitude']:.2f} latitude, {row['longitude']:.2f} longitude, {row['elevation']:.2f} m</h5>"
        html_disp += f"<p style='color:black; font-size:2px; opacity:0;'>Station {index + 1}</p>"

    return f"""
    <div style="max-width: 400px; word-wrap: break-word;">
        {html_disp}
    </div>
    """


def clear_map_draw(map_object):
    # ClearMapDraw().add_to(map_object)
    map_object.add_child(ClearMapDraw())

def add_map_draw(map_object, areas):
    # AddMapDraw(all_drawings=areas) # .add_to(map_object)
    map_object.add_child(AddMapDraw(all_drawings=areas))

class ClearMapDraw(MacroElement):
    def __init__(self):
        super().__init__()
        # Set the Jinja2 template for injecting the JS
        self._template = jinja2.Template("""
        {% macro script(this, kwargs) %}
        console.log("JavaScript is running to clear drawn layers.");  // Debugging console log
        var map = this;  // Reference to the current map object
        if (typeof map.drawnItems !== 'undefined') {
            map.drawnItems.clearLayers();
        } else {
            map.eachLayer(function(layer) {
                if (layer.hasOwnProperty('_path')) {
                    map.removeLayer(layer);
                }
            });
        }
        {% endmacro %}
        """)


class AddMapDraw(MacroElement):
    def __init__(self, all_drawings: List[GeometryConstraint]):
        super().__init__()
        self.all_drawings = all_drawings
        self._template = jinja2.Template("""
        {% macro script(this, kwargs) %}
        console.log("JavaScript is adding drawing layers.");  // Debugging console log
        var map = this;  // Reference to the current map object
                                         
        console.log(this.map)
        console.log(map)

        // Ensure the drawnItems layer group exists
        if (typeof map.drawnItems === 'undefined') {
            map.drawnItems = new L.FeatureGroup();
            map.addLayer(map.drawnItems);
        }

        // Example of adding a rectangle
        {% for drawing in this.all_drawings %}
            {% if drawing.geo_type == 'bounding' %}
                var bounds = [[{{drawing.coords.min_lat}}, {{drawing.coords.min_lng}}], [{{drawing.coords.max_lat}}, {{drawing.coords.max_lng}}]];
                var rect = L.rectangle(bounds, {});
                map.drawnItems.addLayer(rect);
            {% endif %}
            {% if drawing.geo_type == 'circle' %}
                var circ = L.circle([{{drawing.coords.lat}}, {{drawing.coords.lng}}], {radius: {{drawing.coords.max_radius}}});
                map.drawnItems.addLayer(circ);       
            {% endif %}                          
        {% endfor %}

        // More cases for other types like circles, polylines, etc., can be added here
        {% endmacro %}
        """)


class DrawEventHandler(MacroElement):
    def __init__(self):
        super().__init__()
        self._template = jinja2.Template("""
        {% macro script(this, kwargs) %}
        console.log("JavaScript is running to detect drawn layers.");

        // Access the map using the dynamic name provided by Folium
        var map = {{ this._parent.get_name() }};
        console.log("Map instance:", map);

        // Ensure map exists before attaching event listeners
        if (map) {
            console.log('Map instance found:', map);

            // Listen for the draw:created event
            map.on(L.Draw.Event.CREATED, function (e) {
                var layer = e.layer;  // Get the drawn layer (circle, rectangle, etc.)
                var geojsonData = layer.toGeoJSON();
                console.log("Sending data to backend:", geojsonData);
            });
        } else {
            console.log("Map instance not found.");
        }
        {% endmacro %}
        """)


def normalize_bounds(geometry_constraint: GeometryConstraint) -> List[GeometryConstraint]:
    """
    Split bounds of a GeometryConstraint that crosses the 180° meridian or falls partly in a mirrored instance.
    
    Args:
    - geometry_constraint: A GeometryConstraint instance containing RectangleArea bounds.
    
    Returns:
    - A list of GeometryConstraint instances. If the rectangle crosses the 180° meridian or falls in a mirrored instance,
      it will return one or two GeometryConstraints.
    """
    rect_bounds = geometry_constraint.coords
    lat_min, lon_min = rect_bounds.min_lat, rect_bounds.min_lng
    lat_max, lon_max = rect_bounds.max_lat, rect_bounds.max_lng
    if lon_min >= -180 and lon_max <= 180:
        return [geometry_constraint]
    
    elif lon_min < 180 and lon_max > 180:
        left_rectangle = GeometryConstraint(
            coords=RectangleArea(
                min_lat=lat_min,
                max_lat=lat_max,
                min_lng=lon_min,
                max_lng=180
            )
        )
        
        right_rectangle = GeometryConstraint(
            coords=RectangleArea(
                min_lat=lat_min,
                max_lat=lat_max,
                min_lng=-180,
                max_lng=lon_max - 360
            )
        )
        
        return [left_rectangle, right_rectangle]

    elif lon_min < -180 and lon_max <= 180:
        # Normalize the left part to be within [-180, 180] range
        left_rectangle = GeometryConstraint(
            coords=RectangleArea(
                min_lat=lat_min,
                max_lat=lat_max,
                min_lng=lon_min + 360,  
                max_lng=180
            )
        )
        
        # Right side remains within the original range
        main_rectangle = GeometryConstraint(
            coords=RectangleArea(
                min_lat=lat_min,
                max_lat=lat_max,
                min_lng=-180,
                max_lng=lon_max
            )
        )
        print(left_rectangle, main_rectangle)
        return [left_rectangle, main_rectangle]
    
    # Case where both longitudes are less than -180 (entirely in the left mirrored instance)
    elif lon_min < -180 and lon_max < -180:
        normalized_rectangle = GeometryConstraint(
            coords=RectangleArea(
                min_lat=lat_min,
                max_lat=lat_max,
                min_lng=lon_min + 360,
                max_lng=lon_max + 360
            )
        )
        return [normalized_rectangle]
    
    # Case where both longitudes are greater than 180 (entirely in the right mirrored instance)
    elif lon_min > 180 and lon_max > 180:
        normalized_rectangle = GeometryConstraint(
            coords=RectangleArea(
                min_lat=lat_min,
                max_lat=lat_max,
                min_lng=lon_min - 360,
                max_lng=lon_max - 360
            )
        )
        return [normalized_rectangle]


def normalize_circle(geometry_constraint: GeometryConstraint) -> List[GeometryConstraint]:
    """
    Normalize circle bounds for circles that are completely located in the left or right mirrored instance.
    
    Args:
    - geometry_constraint: A GeometryConstraint instance containing CircleArea bounds.
    
    Returns:
    - A list with the normalized GeometryConstraint instance. If the circle falls entirely within the left or right mirrored instance,
      the longitude will be adjusted to bring it within the [-180, 180] range.
    """
    circle = geometry_constraint.coords
    center_lat, center_lng, radius = circle.lat, circle.lng, circle.max_radius

    # Case where the circle is within the main instance or partially overlaps it (no need to modify)
    if -180 <= center_lng <= 180:
        return [geometry_constraint]
    
    # Case where the circle is entirely in the left mirrored instance (center_lng < -180)
    elif center_lng < -180:
        normalized_circle = GeometryConstraint(
            coords=CircleArea(
                lat=center_lat,
                lng=center_lng + 360,  # Normalize center_lng to be within [-180, 180]
                max_radius=radius
            )
        )
        return [normalized_circle]

    # Case where the circle is entirely in the right mirrored instance (center_lng > 180)
    elif center_lng > 180:
        normalized_circle = GeometryConstraint(
            coords=CircleArea(
                lat=center_lat,
                lng=center_lng - 360,  # Normalize center_lng to be within [-180, 180]
                max_radius=radius
            )
        )
        return [normalized_circle]
