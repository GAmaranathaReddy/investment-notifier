#!/usr/bin/env python3
"""
Investment Notifier Web UI
A simple Flask-based UI for viewing and editing symbol configurations.
"""

import json
import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for

app = Flask(__name__, template_folder='templates', static_folder='static')

# Configuration paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
STOCKS_FILE = os.path.join(BASE_DIR, 'stocks.json')
RECOMMENDED_FILE = os.path.join(BASE_DIR, 'recommended_symbols.json')


def load_json(filepath):
    """Load JSON file safely."""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading {filepath}: {e}")
        return None


def save_json(filepath, data):
    """Save data to JSON file with pretty formatting."""
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)


def get_config():
    """Load main config file."""
    return load_json(CONFIG_FILE) or {}


def save_config(config):
    """Save main config file."""
    save_json(CONFIG_FILE, config)


def get_stocks():
    """Load stocks watchlist."""
    return load_json(STOCKS_FILE) or []


def save_stocks(stocks):
    """Save stocks watchlist."""
    save_json(STOCKS_FILE, stocks)


def get_recommended():
    """Load recommended symbols."""
    return load_json(RECOMMENDED_FILE) or {}


# =============================================================================
# Web Routes
# =============================================================================

@app.route('/')
def index():
    """Main dashboard showing all symbol configurations."""
    config = get_config()
    stocks = get_stocks()
    recommended = get_recommended()

    # Extract categories with their symbols
    categories = {}
    if 'categories' in config:
        for cat_name, cat_data in config['categories'].items():
            cat_info = {
                'description': cat_data.get('description', ''),
                'symbols': cat_data.get('symbols', []),
                'baskets': cat_data.get('baskets', {})
            }
            categories[cat_name] = cat_info

    return render_template('index.html',
                         categories=categories,
                         stocks=stocks,
                         recommended=recommended)


@app.route('/api/stocks', methods=['GET'])
def api_get_stocks():
    """API: Get all stocks in watchlist."""
    return jsonify(get_stocks())


@app.route('/api/stocks', methods=['POST'])
def api_add_stock():
    """API: Add a symbol to stocks watchlist."""
    data = request.get_json()
    symbol = data.get('symbol', '').upper().strip()

    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400

    stocks = get_stocks()
    if symbol in stocks:
        return jsonify({'error': 'Symbol already exists'}), 400

    stocks.append(symbol)
    stocks.sort()
    save_stocks(stocks)

    return jsonify({'success': True, 'stocks': stocks})


@app.route('/api/stocks/<symbol>', methods=['DELETE'])
def api_delete_stock(symbol):
    """API: Remove a symbol from stocks watchlist."""
    symbol = symbol.upper()
    stocks = get_stocks()

    if symbol not in stocks:
        return jsonify({'error': 'Symbol not found'}), 404

    stocks.remove(symbol)
    save_stocks(stocks)

    return jsonify({'success': True, 'stocks': stocks})


@app.route('/api/categories', methods=['GET'])
def api_get_categories():
    """API: Get all categories and their symbols."""
    config = get_config()
    return jsonify(config.get('categories', {}))


@app.route('/api/categories/<category>/symbols', methods=['POST'])
def api_add_category_symbol(category):
    """API: Add a symbol to a category."""
    data = request.get_json()
    symbol = data.get('symbol', '').upper().strip()

    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400

    config = get_config()

    if category not in config.get('categories', {}):
        return jsonify({'error': 'Category not found'}), 404

    cat_data = config['categories'][category]

    # Handle direct symbols list
    if 'symbols' in cat_data:
        if symbol in cat_data['symbols']:
            return jsonify({'error': 'Symbol already exists in category'}), 400
        cat_data['symbols'].append(symbol)
        cat_data['symbols'].sort()
    else:
        # Initialize symbols list if it doesn't exist
        cat_data['symbols'] = [symbol]

    save_config(config)
    return jsonify({'success': True, 'symbols': cat_data.get('symbols', [])})


@app.route('/api/categories/<category>/symbols/<symbol>', methods=['DELETE'])
def api_delete_category_symbol(category, symbol):
    """API: Remove a symbol from a category."""
    symbol = symbol.upper()
    config = get_config()

    if category not in config.get('categories', {}):
        return jsonify({'error': 'Category not found'}), 404

    cat_data = config['categories'][category]

    if 'symbols' not in cat_data or symbol not in cat_data['symbols']:
        return jsonify({'error': 'Symbol not found in category'}), 404

    cat_data['symbols'].remove(symbol)
    save_config(config)

    return jsonify({'success': True, 'symbols': cat_data.get('symbols', [])})


@app.route('/api/categories/<category>/baskets/<basket>', methods=['POST'])
def api_add_basket_symbol(category, basket):
    """API: Add a symbol to a basket within a category."""
    data = request.get_json()
    symbol = data.get('symbol', '').upper().strip()

    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400

    config = get_config()

    if category not in config.get('categories', {}):
        return jsonify({'error': 'Category not found'}), 404

    cat_data = config['categories'][category]

    if 'baskets' not in cat_data or basket not in cat_data['baskets']:
        return jsonify({'error': 'Basket not found'}), 404

    if symbol in cat_data['baskets'][basket]:
        return jsonify({'error': 'Symbol already exists in basket'}), 400

    cat_data['baskets'][basket].append(symbol)
    cat_data['baskets'][basket].sort()
    save_config(config)

    return jsonify({'success': True, 'symbols': cat_data['baskets'][basket]})


@app.route('/api/categories/<category>/baskets/<basket>/<symbol>', methods=['DELETE'])
def api_delete_basket_symbol(category, basket, symbol):
    """API: Remove a symbol from a basket."""
    symbol = symbol.upper()
    config = get_config()

    if category not in config.get('categories', {}):
        return jsonify({'error': 'Category not found'}), 404

    cat_data = config['categories'][category]

    if 'baskets' not in cat_data or basket not in cat_data['baskets']:
        return jsonify({'error': 'Basket not found'}), 404

    if symbol not in cat_data['baskets'][basket]:
        return jsonify({'error': 'Symbol not found in basket'}), 404

    cat_data['baskets'][basket].remove(symbol)
    save_config(config)

    return jsonify({'success': True, 'symbols': cat_data['baskets'][basket]})


@app.route('/api/recommended', methods=['GET'])
def api_get_recommended():
    """API: Get recommended symbols."""
    return jsonify(get_recommended())


@app.route('/api/config', methods=['GET'])
def api_get_config():
    """API: Get full config."""
    return jsonify(get_config())


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs(os.path.join(BASE_DIR, 'templates'), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, 'static'), exist_ok=True)

    print("=" * 60)
    print("Investment Notifier - Symbol Configuration UI")
    print("=" * 60)
    print(f"Config file: {CONFIG_FILE}")
    print(f"Stocks file: {STOCKS_FILE}")
    print(f"Recommended file: {RECOMMENDED_FILE}")
    print("=" * 60)
    print("Starting server at http://localhost:5050")
    print("=" * 60)

    app.run(host='0.0.0.0', port=5050, debug=True)
