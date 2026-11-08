from math import cos, pi, sin, sqrt
from .external_schemas import Coordinates


def mainland_gcj02(location):
    """Convert mainland WGS84 to GCJ-02 for weather-grid lookup, not navigation."""
    lon, lat = location.longitude, location.latitude
    if not (72.004 <= lon <= 137.8347 and 0.8293 <= lat <= 55.8271):
        return location
    x, y = lon - 105, lat - 35
    dlat = -100 + 2*x + 3*y + .2*y*y + .1*x*y + .2*sqrt(abs(x))
    dlat += (20*sin(6*x*pi)+20*sin(2*x*pi))*2/3
    dlat += (20*sin(y*pi)+40*sin(y*pi/3))*2/3
    dlat += (160*sin(y*pi/12)+320*sin(y*pi/30))*2/3
    dlon = 300+x+2*y+.1*x*x+.1*x*y+.1*sqrt(abs(x))
    dlon += (20*sin(6*x*pi)+20*sin(2*x*pi))*2/3
    dlon += (20*sin(x*pi)+40*sin(x*pi/3))*2/3
    dlon += (150*sin(x*pi/12)+300*sin(x*pi/30))*2/3
    rad = lat*pi/180
    magic = 1-.00669342162296594323*sin(rad)**2
    dlat = dlat*180/((6335552.717000426/(magic*sqrt(magic)))*pi)
    dlon = dlon*180/((6378245/sqrt(magic))*cos(rad)*pi)
    return Coordinates(longitude=lon+dlon, latitude=lat+dlat)
