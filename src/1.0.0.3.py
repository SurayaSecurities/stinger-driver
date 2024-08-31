import traceback
from flask import Flask, jsonify, request, render_template
import threading
import MetaTrader5 as mt5
from datetime import datetime
from dotenv import load_dotenv
import os
import socket

# Load environment variables from .env file
load_dotenv()

# Access environment variables
mt5_login = os.getenv("MT5_LOGIN")
mt5_password = os.getenv("MT5_PASSWORD")
mt5_server = os.getenv("MT5_SERVER")

app = Flask(__name__)

# Initialize and connect to MetaTrader 5
def initialize_mt5():
    print("[INFO]\tInitializing MetaTrader 5...")
    if not mt5.initialize(login=int(mt5_login), password=mt5_password, server=mt5_server):
        error_code, description = mt5.last_error()
        print(f"[ERROR]\tFailed to initialize MetaTrader 5: {error_code} - {description}")
        return False
    print("[INFO]\tMetaTrader 5 initialized successfully")
    account_info = mt5.account_info()
    if account_info is None:
        error_code, description = mt5.last_error()
        print(f"[ERROR]\tFailed to retrieve account info: {error_code} - {description}")
        return False
    print(f"[INFO]\tConnected to account {account_info.login} on server {mt5_server}")
    return True

# Global variables to store incoming messages in a structured format
ohlc_data = []
trades_data = []

# Function to handle incoming socket connections
def socket_server():
    global ohlc_data, trades_data
    serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    try:
        # Bind to the specified address and port
        serversocket.bind(('localhost', 8888))
        print("[INFO]\tServer successfully bound to port 8888")

        # Start listening for incoming connections
        serversocket.listen(7000)
        print("[INFO]\tServer is now listening for connections")

        while True:
            # Accept a connection
            connection, addr = serversocket.accept()
            print("[INFO]\tConnection established with:", addr)

            msg = ''
            while not "END CONNECTION\0" in msg:
                try:
                    # Receive data from the connection
                    data = connection.recv(1024)
                    if not data:
                        break
                    msg = data.decode().strip()
                    # print("[INFO]\tReceived Message:", msg)

                    # Process and store the data
                    if "OHLC" in msg:
                        # Split the message into key-value pairs
                        ohlc_values = msg.split(" ")

                        # Debug print to verify the message structure
                        # print(f"[DEBUG]\tProcessing OHLC values: {ohlc_values}")

                        if len(ohlc_values) >= 6:
                            try:
                                current_time = datetime.utcnow().isoformat() + 'Z'  # Current UTC time in ISO format
                                ohlc_entry = {
                                    "symbol": ohlc_values[0].split(':')[0],
                                    "open": float(ohlc_values[2].split('=')[1].replace("\x00", "")),
                                    "high": float(ohlc_values[3].split('=')[1].replace("\x00", "")),
                                    "low": float(ohlc_values[4].split('=')[1].replace("\x00", "")),
                                    "close": float(ohlc_values[5].split('=')[1].replace("\x00", "")),
                                    "time": current_time
                                }
                                ohlc_data.append(ohlc_entry)
                                # print(f"[INFO]\tOHLC data stored: {ohlc_entry}")
                            except IndexError:
                                # print("[ERROR]\tUnexpected format in OHLC data")
                                print()
                            except ValueError:
                                # print("[ERROR]\tInvalid number format in OHLC data")
                                print()
                    elif "Open Trades" in msg:
                        trades = msg.split("\n")[1:]
                        # print(f"[DEBUG]\tProcessing Trade values: {trades}")
                        
                        for trade in trades:
                            if trade:
                                trade_values = trade.split(" ")
                                try:
                                    trade_entry = {
                                        "ticket": int(trade_values[0].split('=')[1].replace("\x00", "")),
                                        "symbol": trade_values[1].split('=')[1],
                                        "volume": float(trade_values[2].split('=')[1].replace("\x00", "")),
                                        "open_price": float(trade_values[3].split('=')[1].replace("\x00", "")),
                                        "current_price": float(trade_values[4].split('=')[1].replace("\x00", "")),
                                        "time": datetime.utcnow().isoformat() + 'Z'  # Current UTC time in ISO format
                                    }
                                    trades_data.append(trade_entry)
                                    # print(f"[INFO]\tTrade data stored: {trade_entry}")
                                except (IndexError, ValueError):
                                    # print("[ERROR]\tError processing trade data")
                                    print('')

                except socket.error as e:
                    print("[ERROR]\tSocket error:", e)
                    break

    except socket.error as e:
        print("[ERROR]\tFailed to bind or listen:", e)

    finally:
        # Close the connection and the server socket
        connection.close()
        serversocket.close()
        print("[INFO]\tServer socket closed")

# Start the socket server in a separate thread
threading.Thread(target=socket_server, daemon=True).start()

# Flask endpoint to serve the OHLC data in JSON format
@app.route('/api/v1/data/ohlc', methods=['GET'])
def get_ohlc_data():
    if ohlc_data:
        return jsonify(ohlc_data[-1])  # Return the latest OHLC data
    else:
        print("[ERROR]\tNo OHLC data available")
        return jsonify({"error": "No OHLC data available"}), 404

# Flask endpoint to serve the Trades data in JSON format
@app.route('/api/v1/data/trades', methods=['GET'])
def get_trades_data():
    if trades_data:
        return jsonify(trades_data)  # Return all trades data
    else:
        print("[ERROR]\tNo trades data available")
        return jsonify({"error": "No trades data available"}), 404

@app.route('/api/v1/trade/history', methods=['GET'])
def get_trading_history():
    try:
        # Initialize MetaTrader 5
        if not mt5.initialize():
            return jsonify({"error": "MetaTrader5 initialization failed"}), 500
        
        # Get query parameters
        from_date = request.args.get('from_date')
        to_date = request.args.get('to_date')

        # Convert dates from string to datetime if provided
        from_datetime = datetime.strptime(from_date, "%Y-%m-%d") if from_date else datetime(1970, 1, 1)
        to_datetime = datetime.strptime(to_date, "%Y-%m-%d") if to_date else datetime.now()

        # Fetch the trading history deals
        history = mt5.history_deals_get(from_datetime, to_datetime)
        if history is None:
            return jsonify({"error": "Failed to retrieve trading history"}), 500

        # Simplified output
        history_list = []
        for deal in history:
            history_list.append({
                "ticket": deal.ticket,
                "symbol": deal.symbol,
                "type": deal.type,
                "volume": deal.volume,
                "price": deal.price,
                "profit": deal.profit,
                "time": datetime.fromtimestamp(deal.time).strftime('%Y-%m-%d %H:%M:%S'),
                "comment": deal.comment
            })

        return jsonify({"trading_history": history_list}), 200

    except Exception as e:
        # Log detailed error information
        print(f"[ERROR]\tError retrieving trading history: {e}")
        print(traceback.format_exc())  # Print stack trace for detailed debugging
        return jsonify({"error": "Failed to retrieve trading history"}), 500

    finally:
        # Ensure MetaTrader 5 is properly shut down after request
        mt5.shutdown()
         
@app.route('/api/v1/account/balance', methods=['GET'])
def get_account_balance():
    try:
        # Fetch account information
        account_info = mt5.account_info()

        if account_info is None:
            return jsonify({"error": "Failed to retrieve account information"}), 500

        # Extract relevant information
        account_data = {
            "account": account_info.login,
            "balance": account_info.balance,
            "equity": account_info.equity,
            "margin": account_info.margin,
            "free_margin": account_info.margin_free,
            "margin_level": account_info.margin_level
        }

        return jsonify({"account_info": account_data}), 200

    except Exception as e:
        print(f"[ERROR]\tError retrieving account balance: {e}")
        return jsonify({"error": "Failed to retrieve account balance"}), 500


# Flask endpoint to open a trade
@app.route('/api/v1/trade/open', methods=['POST'])
def open_trade():
    try:
        trade_info = request.json  # Get the JSON data from the POST request
        print("[INFO]\tReceived trade open request:", trade_info)

        # Validate the incoming data
        required_fields = ["symbol", "volume", "type"]
        for field in required_fields:
            if field not in trade_info:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        symbol = trade_info["symbol"]
        volume = trade_info["volume"]
        order_type_str = trade_info["type"].upper()
        order_type = mt5.ORDER_TYPE_BUY  # Default to buy order

        # Determine order type
        if order_type_str == "SELL":
            order_type = mt5.ORDER_TYPE_SELL
        elif order_type_str == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
        elif order_type_str == "BUY_LIMIT":
            order_type = mt5.ORDER_TYPE_BUY_LIMIT
        elif order_type_str == "SELL_LIMIT":
            order_type = mt5.ORDER_TYPE_SELL_LIMIT
        elif order_type_str == "BUY_STOP":
            order_type = mt5.ORDER_TYPE_BUY_STOP
        elif order_type_str == "SELL_STOP":
            order_type = mt5.ORDER_TYPE_SELL_STOP
        else:
            return jsonify({"error": "Invalid order type"}), 400

        # Optional parameters
        stoploss = trade_info.get("stoploss")
        takeprofit = trade_info.get("takeprofit")

        # Log details before sending order
        print(f"[INFO]\tPreparing to send order: Symbol={symbol}, Volume={volume}, Type={order_type_str}")

        # Check if symbol is available
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            print(f"[ERROR]\tSymbol {symbol} not found")
            return jsonify({"error": f"Symbol {symbol} not found"}), 404

        # Check if the symbol is available for trading
        if not symbol_info.visible:
            print(f"[INFO]\tSymbol {symbol} is not visible, trying to enable it")
            if not mt5.symbol_select(symbol, True):
                print(f"[ERROR]\tFailed to select symbol {symbol}")
                return jsonify({"error": f"Failed to select symbol {symbol}"}), 500

        # Get the current market price
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            print(f"[ERROR]\tFailed to get market tick for symbol {symbol}")
            return jsonify({"error": f"Failed to get market tick for symbol {symbol}"}), 500

        if order_type == mt5.ORDER_TYPE_BUY or order_type == mt5.ORDER_TYPE_BUY_LIMIT or order_type == mt5.ORDER_TYPE_BUY_STOP:
            price = tick.ask
            if stoploss:
                stoploss_price = price - stoploss * symbol_info.point
            if takeprofit:
                takeprofit_price = price + takeprofit * symbol_info.point
        elif order_type == mt5.ORDER_TYPE_SELL or order_type == mt5.ORDER_TYPE_SELL_LIMIT or order_type == mt5.ORDER_TYPE_SELL_STOP:
            price = tick.bid
            if stoploss:
                stoploss_price = price + stoploss * symbol_info.point
            if takeprofit:
                takeprofit_price = price - takeprofit * symbol_info.point

        # Prepare and send the order request to MetaTrader 5
        order_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": 234000,
            "comment": "Trade from Flask API",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
            "stoplimit": stoploss_price if stoploss else None,
            "takeprofit": takeprofit_price if takeprofit else None
        }

        result = mt5.order_send(order_request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"[ERROR]\tFailed to open trade: {result.retcode}, Comment: {result.comment}")
            return jsonify({"error": f"Failed to open trade: {result.comment}"}), 500

        print(f"[INFO]\tTrade opened successfully: {result}")
        return jsonify({"message": "Trade opened successfully", "order": result.order}), 200

    except Exception as e:
        print(f"[ERROR]\tError opening trade: {e}")
        return jsonify({"error": "Failed to open trade"}), 500

# Flask endpoint to close a trade
@app.route('/api/v1/trade/close', methods=['POST'])
def close_trade():
    try:
        trade_info = request.json  # Get the JSON data from the POST request
        print("[INFO]\tReceived trade close request:", trade_info)

        if "ticket" not in trade_info:
            return jsonify({"error": "Invalid trade data"}), 400

        ticket = trade_info["ticket"]

        # Retrieve the position to close
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            print(f"[ERROR]\tPosition with ticket {ticket} not found")
            return jsonify({"error": "Trade not found"}), 404

        position = positions[0]
        symbol = position.symbol
        volume = position.volume
        order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY

        # Prepare and send the close request
        close_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "position": ticket,
            "price": mt5.symbol_info_tick(symbol).bid if order_type == mt5.ORDER_TYPE_SELL else mt5.symbol_info_tick(symbol).ask,
            "deviation": 20,
            "magic": 234000,
            "comment": "Close trade from Flask API",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(close_request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"[ERROR]\tFailed to close trade: {result.retcode}, Comment: {result.comment}")
            return jsonify({"error": f"Failed to close trade: {result.comment}"}), 500

        print(f"[INFO]\tTrade closed successfully: {result}")
        return jsonify({"message": "Trade closed successfully", "order": result.order}), 200

    except Exception as e:
        print(f"[ERROR]\tError closing trade: {e}")
        return jsonify({"error": "Failed to close trade"}), 500

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    if initialize_mt5():
        threading.Thread(target=socket_server, daemon=True).start()
        app.run(host='0.0.0.0', port=5000)
    else:
        print("[ERROR]\tFailed to initialize MetaTrader 5. Exiting...")

