from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from datetime import datetime
import os
import math
import statistics

app = Flask(__name__)
CORS(app)

# Подключение к базе данных PostgreSQL
DATABASE_URL = os.getenv('DATABASE_URL')
if DATABASE_URL is None:
    raise ValueError("DATABASE_URL environment variable is not set")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class WifiPoint(Base):
    __tablename__ = "wifi_points"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    password = Column(String)
    mac_address = Column(String, unique=True, index=True)
    encryption_type = Column(String)
    lat = Column(Float)
    lng = Column(Float)
    confidence_level = Column(Float, default=0.0)  # Уровень уверенности в координатах
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Связь с измерениями сигнала
    signal_measurements = relationship("SignalMeasurement", back_populates="wifi_point")

class SignalMeasurement(Base):
    __tablename__ = "signal_measurements"
    
    id = Column(Integer, primary_key=True, index=True)
    wifi_point_id = Column(Integer, ForeignKey("wifi_points.id"))
    lat = Column(Float)  # Координаты откуда был замерен сигнал
    lng = Column(Float)
    rssi = Column(Integer)  # Мощность сигнала в dBm
    distance_estimate = Column(Float)  # Расчетная дистанция на основе RSSI
    measured_at = Column(DateTime, default=datetime.utcnow)
    
    # Связь с точкой доступа
    wifi_point = relationship("WifiPoint", back_populates="signal_measurements")

# Создание таблиц
Base.metadata.create_all(bind=engine)

def get_db():
    """Получить сессию базы данных"""
    db = SessionLocal()
    try:
        return db
    finally:
        pass

def estimate_distance_from_rssi(rssi, tx_power=-30):
    """
    Оценка расстояния на основе RSSI
    tx_power: мощность передатчика в dBm (обычно -30 dBm для WiFi роутеров)
    rssi: принятая мощность сигнала в dBm
    """
    if rssi == 0:
        return -1.0
    
    ratio = tx_power / rssi
    if ratio < 1.0:
        return math.pow(ratio, 10)
    else:
        accuracy = (0.89976) * math.pow(ratio, 7.7095) + 0.111
        return accuracy

def calculate_centroid_from_measurements(measurements):
    """
    Вычисление центра масс на основе множественных измерений RSSI
    Использует взвешенное среднее, где вес = 1/distance^2
    """
    if len(measurements) < 2:
        return None, 0.0
    
    weighted_lat_sum = 0
    weighted_lng_sum = 0
    total_weight = 0
    
    for measurement in measurements:
        # Чем ближе точка (меньше distance), тем больше ее вес
        weight = 1.0 / (measurement.distance_estimate ** 2 + 0.1)  # +0.1 для избежания деления на ноль
        
        weighted_lat_sum += measurement.lat * weight
        weighted_lng_sum += measurement.lng * weight
        total_weight += weight
    
    if total_weight == 0:
        return None, 0.0
    
    # Вычисляем взвешенные координаты
    centroid_lat = weighted_lat_sum / total_weight
    centroid_lng = weighted_lng_sum / total_weight
    
    # Рассчитываем уровень уверенности на основе количества измерений и их разброса
    confidence = min(len(measurements) / 5.0, 1.0)  # Максимальная уверенность при 5+ измерениях
    
    return (centroid_lat, centroid_lng), confidence

def triangulate_position(measurements):
    """
    Алгоритм триангуляции на основе нескольких измерений RSSI
    Возвращает наиболее вероятные координаты точки доступа
    """
    if len(measurements) < 3:
        # Если меньше 3 измерений, используем взвешенное среднее
        return calculate_centroid_from_measurements(measurements)
    
    # Для триангуляции нужно минимум 3 точки
    # Используем метод наименьших квадратов для нахождения пересечения окружностей
    
    points = []
    for measurement in measurements:
        points.append({
            'x': measurement.lat,
            'y': measurement.lng, 
            'r': measurement.distance_estimate
        })
    
    # Упрощенный алгоритм триангуляции для первых трех лучших измерений
    # В реальном приложении можно использовать более сложные алгоритмы
    best_measurements = sorted(measurements, key=lambda m: m.distance_estimate)[:3]
    
    return calculate_centroid_from_measurements(best_measurements)

@app.route('/')
def index():
    """Главная страница с картой"""
    return render_template('index.html')

@app.route('/points')
def points_list():
    """Страница со списком всех точек доступа"""
    db = get_db()
    try:
        points = db.query(WifiPoint).all()
        # Преобразуем в формат для шаблона
        points_data = []
        for point in points:
            points_data.append({
                'id': point.id,
                'name': point.name,
                'password': point.password,
                'mac_address': point.mac_address,
                'encryption_type': point.encryption_type,
                'lat': point.lat,
                'lng': point.lng,
                'confidence_level': point.confidence_level,
                'measurement_count': len(point.signal_measurements)
            })
        return render_template('points.html', points=points_data)
    finally:
        db.close()

@app.route('/api/points', methods=['GET'])
def get_points():
    """API для получения всех точек доступа"""
    db = get_db()
    try:
        points = db.query(WifiPoint).all()
        points_data = []
        for point in points:
            points_data.append({
                'id': point.id,
                'name': point.name,
                'password': point.password,
                'mac_address': point.mac_address,
                'encryption_type': point.encryption_type,
                'lat': point.lat,
                'lng': point.lng,
                'confidence_level': point.confidence_level,
                'measurement_count': len(point.signal_measurements),
                'created_at': point.created_at.isoformat() if point.created_at is not None else None,
                'updated_at': point.updated_at.isoformat() if point.updated_at is not None else None
            })
        return jsonify(points_data)
    finally:
        db.close()

@app.route('/api/add_point', methods=['GET'])
def add_point():
    """API для добавления точки доступа через GET запрос"""
    db = get_db()
    try:
        # Получаем обязательные параметры
        lat_str = request.args.get('lat')
        lng_str = request.args.get('lng')
        mac_address = request.args.get('mac')
        
        if lat_str is None or lng_str is None:
            return jsonify({'success': False, 'error': 'Параметры lat и lng обязательны.'}), 400
            
        if mac_address is None:
            return jsonify({'success': False, 'error': 'Параметр mac (MAC-адрес) обязателен.'}), 400
            
        lat = float(lat_str)
        lng = float(lng_str)
        
        # Получаем опциональные параметры
        name = request.args.get('name', 'Безымянная точка')
        password = request.args.get('password', '')
        encryption_type = request.args.get('encryption_type', 'Unknown')
        rssi_str = request.args.get('rssi')
        
        # Проверяем, существует ли уже точка с таким MAC-адресом
        existing_point = db.query(WifiPoint).filter(WifiPoint.mac_address == mac_address).first()
        
        if existing_point:
            # Точка существует - добавляем новое измерение и пересчитываем координаты
            rssi = int(rssi_str) if rssi_str else -50  # Значение по умолчанию
            distance = estimate_distance_from_rssi(rssi)
            
            # Создаем новое измерение
            new_measurement = SignalMeasurement(
                wifi_point_id=existing_point.id,
                lat=lat,
                lng=lng,
                rssi=rssi,
                distance_estimate=distance
            )
            db.add(new_measurement)
            db.flush()  # Получаем ID измерения
            
            # Получаем все измерения для этой точки
            all_measurements = db.query(SignalMeasurement).filter(
                SignalMeasurement.wifi_point_id == existing_point.id
            ).all()
            
            # Пересчитываем координаты на основе всех измерений
            position_result, confidence = triangulate_position(all_measurements)
            
            if position_result:
                existing_point.lat = position_result[0]
                existing_point.lng = position_result[1]
                existing_point.confidence_level = confidence
                existing_point.updated_at = datetime.utcnow()
                
                # Обновляем остальные поля если они указаны
                if request.args.get('name'):
                    existing_point.name = name
                if request.args.get('password'):
                    existing_point.password = password
                if request.args.get('encryption_type'):
                    existing_point.encryption_type = encryption_type
            
            db.commit()
            
            return jsonify({
                'success': True, 
                'action': 'updated',
                'point': {
                    'id': existing_point.id,
                    'name': existing_point.name,
                    'password': existing_point.password,
                    'mac_address': existing_point.mac_address,
                    'encryption_type': existing_point.encryption_type,
                    'lat': existing_point.lat,
                    'lng': existing_point.lng,
                    'confidence_level': existing_point.confidence_level,
                    'measurement_count': len(all_measurements)
                }
            })
        else:
            # Создаем новую точку доступа
            new_point = WifiPoint(
                name=name,
                password=password,
                mac_address=mac_address,
                encryption_type=encryption_type,
                lat=lat,
                lng=lng,
                confidence_level=0.1  # Низкая уверенность для первого измерения
            )
            
            db.add(new_point)
            db.flush()  # Получаем ID новой точки
            
            # Добавляем первое измерение если указан RSSI
            if rssi_str:
                rssi = int(rssi_str)
                distance = estimate_distance_from_rssi(rssi)
                
                first_measurement = SignalMeasurement(
                    wifi_point_id=new_point.id,
                    lat=lat,
                    lng=lng,
                    rssi=rssi,
                    distance_estimate=distance
                )
                db.add(first_measurement)
            
            db.commit()
            
            return jsonify({
                'success': True, 
                'action': 'created',
                'point': {
                    'id': new_point.id,
                    'name': new_point.name,
                    'password': new_point.password,
                    'mac_address': new_point.mac_address,
                    'encryption_type': new_point.encryption_type,
                    'lat': new_point.lat,
                    'lng': new_point.lng,
                    'confidence_level': new_point.confidence_level,
                    'measurement_count': 1 if rssi_str else 0
                }
            })
    
    except (TypeError, ValueError) as e:
        return jsonify({'success': False, 'error': f'Неверные параметры: {str(e)}'}), 400
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': f'Ошибка сервера: {str(e)}'}), 500
    finally:
        db.close()

@app.route('/api/add_point', methods=['POST'])
def add_point_post():
    """API для добавления точки доступа через POST запрос"""
    db = get_db()
    try:
        data = request.get_json()
        
        # Обязательные параметры
        lat = float(data.get('lat'))
        lng = float(data.get('lng'))
        mac_address = data.get('mac_address')
        
        if not mac_address:
            return jsonify({'success': False, 'error': 'MAC-адрес обязателен.'}), 400
        
        # Опциональные параметры
        name = data.get('name', 'Безымянная точка')
        password = data.get('password', '')
        encryption_type = data.get('encryption_type', 'Unknown')
        rssi = data.get('rssi')
        
        # Аналогичная логика как в GET endpoint
        existing_point = db.query(WifiPoint).filter(WifiPoint.mac_address == mac_address).first()
        
        if existing_point:
            # Обновляем существующую точку
            if rssi is not None:
                distance = estimate_distance_from_rssi(int(rssi))
                new_measurement = SignalMeasurement(
                    wifi_point_id=existing_point.id,
                    lat=lat,
                    lng=lng,
                    rssi=int(rssi),
                    distance_estimate=distance
                )
                db.add(new_measurement)
                db.flush()
                
                all_measurements = db.query(SignalMeasurement).filter(
                    SignalMeasurement.wifi_point_id == existing_point.id
                ).all()
                
                position_result, confidence = triangulate_position(all_measurements)
                
                if position_result:
                    existing_point.lat = position_result[0]
                    existing_point.lng = position_result[1]
                    existing_point.confidence_level = confidence
                    existing_point.updated_at = datetime.utcnow()
            
            # Обновляем остальные поля
            existing_point.name = name
            existing_point.password = password
            existing_point.encryption_type = encryption_type
            
            db.commit()
            
            measurement_count = db.query(SignalMeasurement).filter(
                SignalMeasurement.wifi_point_id == existing_point.id
            ).count()
            
            return jsonify({
                'success': True, 
                'action': 'updated',
                'point': {
                    'id': existing_point.id,
                    'name': existing_point.name,
                    'password': existing_point.password,
                    'mac_address': existing_point.mac_address,
                    'encryption_type': existing_point.encryption_type,
                    'lat': existing_point.lat,
                    'lng': existing_point.lng,
                    'confidence_level': existing_point.confidence_level,
                    'measurement_count': measurement_count
                }
            })
        else:
            # Создаем новую точку
            new_point = WifiPoint(
                name=name,
                password=password,
                mac_address=mac_address,
                encryption_type=encryption_type,
                lat=lat,
                lng=lng,
                confidence_level=0.1
            )
            
            db.add(new_point)
            db.flush()
            
            if rssi is not None:
                distance = estimate_distance_from_rssi(int(rssi))
                first_measurement = SignalMeasurement(
                    wifi_point_id=new_point.id,
                    lat=lat,
                    lng=lng,
                    rssi=int(rssi),
                    distance_estimate=distance
                )
                db.add(first_measurement)
            
            db.commit()
            
            return jsonify({
                'success': True, 
                'action': 'created',
                'point': {
                    'id': new_point.id,
                    'name': new_point.name,
                    'password': new_point.password,
                    'mac_address': new_point.mac_address,
                    'encryption_type': new_point.encryption_type,
                    'lat': new_point.lat,
                    'lng': new_point.lng,
                    'confidence_level': new_point.confidence_level,
                    'measurement_count': 1 if rssi else 0
                }
            })
    
    except (TypeError, ValueError, AttributeError) as e:
        return jsonify({'success': False, 'error': f'Неверные параметры: {str(e)}'}), 400
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': f'Ошибка сервера: {str(e)}'}), 500
    finally:
        db.close()

@app.route('/api/measurements/<int:point_id>', methods=['GET'])
def get_measurements(point_id):
    """API для получения всех измерений конкретной точки доступа"""
    db = get_db()
    try:
        measurements = db.query(SignalMeasurement).filter(
            SignalMeasurement.wifi_point_id == point_id
        ).order_by(SignalMeasurement.measured_at.desc()).all()
        
        measurements_data = []
        for measurement in measurements:
            measurements_data.append({
                'id': measurement.id,
                'lat': measurement.lat,
                'lng': measurement.lng,
                'rssi': measurement.rssi,
                'distance_estimate': measurement.distance_estimate,
                'measured_at': measurement.measured_at.isoformat()
            })
        
        return jsonify({
            'success': True,
            'measurements': measurements_data,
            'total_count': len(measurements_data)
        })
    finally:
        db.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5055, debug=True)