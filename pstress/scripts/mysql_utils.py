#!/bin/python

import os
import subprocess
import time
import shutil
import shlex

def find_mysqld(basedir):
    """Find mysqld or mysqld-debug in basedir/bin."""
    for binary in ["mysqld", "mysqld-debug"]:
        path = os.path.join(basedir, "bin", binary)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            print(f"[INFO] Using {path} binary")
            return path
    raise FileNotFoundError(f"Neither mysqld-debug nor mysqld found in {basedir}/bin")

def init_datadir(mysqld_path, basedir, data_dir, log_file):
    if os.path.exists(data_dir):
        print("[INFO] Removing old datadir...")
        shutil.rmtree(data_dir)
    os.makedirs(data_dir, exist_ok=True)

    print("[INFO] Initializing datadir...")
    with open(log_file, "w") as f:  # write to the .mysqld log file
        subprocess.check_call([
            mysqld_path,
            f"--datadir={data_dir}",
            f"--basedir={basedir}",
            "--initialize-insecure"
        ], stdout=f, stderr=subprocess.STDOUT)
    print(f"[INFO] Datadir initialized (logs -> {log_file})")

def copy_datadir(src_dir, dest_dir):
    """
    Copy a MySQL datadir from src_dir to dest_dir.
    If dest_dir exists, it will be removed before copying.
    """
    if not os.path.exists(src_dir):
        raise FileNotFoundError(f"Source datadir not found: {src_dir}")

    if os.path.exists(dest_dir):
        print("[INFO] Removing old destination datadir...")
        shutil.rmtree(dest_dir)

    print(f"[INFO] Copying datadir from {src_dir} -> {dest_dir} ...")
    shutil.copytree(src_dir, dest_dir, symlinks=True)
    print("[INFO] Datadir copy complete.")

def start_mysqld(mysqld_path, basedir, data_dir, port, err_log, params):
    """Start mysqld with RocksDB enabled, redirect logs to file."""

    params_list = shlex.split(params) if params else []

    with open(err_log, "w"):
        pass  # truncate file automatically

    proc = subprocess.Popen(
        [
        mysqld_path,
        f"--datadir={data_dir}",
        f"--basedir={basedir}",
        f"--port={port}",
        "--skip-networking=0",
        "--socket=mysql.sock",
        "--plugin-load-add=RocksDB=ha_rocksdb.so",
        f"--log-error={err_log}",
        "--rocksdb"
        ] + params_list
    )

    print(f"[INFO] mysqld started with params={params}")
    print(f"[INFO] mysqld started with RocksDB enabled (pid={proc.pid}), logs -> {err_log}")
    return proc

def wait_for_mysql(basedir, port, timeout=30):
    """Wait until MySQL server is ready using mysql client."""
    mysql_client = os.path.join(basedir, "bin", "mysql")
    last_error = None

    for i in range(timeout):
        try:
            subprocess.run(
                [mysql_client, "-u", "root", f"--port={port}", "--protocol=tcp", "-e", "SELECT 1"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True
            )
            print("[INFO] mysqld is ready for queries.")
            return
        except subprocess.CalledProcessError as e:
            last_error = e.stderr.strip()
            if (i + 1) % 5 == 0:  # print only every 5 seconds
                print("[WARN] MySQL not ready yet. Error:", last_error)
            time.sleep(1)

    raise RuntimeError(f"MySQL did not start in time. Last error: {last_error}")

def wait_for_mysql_or_crash(basedir, port, err_log, timeout=30):
    """
    Wait until MySQL is ready to accept connections, or detect crash from error log.

    Args:
        basedir: MySQL base directory (mysql client in bin/)
        port: MySQL port
        err_log: Path to error log
        timeout: Seconds to wait before giving up
    Raises:
        RuntimeError if MySQL crashes or doesn't start in time
    """
    mysql_client = os.path.join(basedir, "bin", "mysql")
    last_error = None
    start_time = time.time()

    # Open error log to tail
    with open(err_log, "r") as f:
        # Seek to end so we only see new lines
        f.seek(0, os.SEEK_END)

        while True:
            # Check timeout
            if time.time() - start_time > timeout:
                raise RuntimeError(f"MySQL did not start in {timeout}s. Last error: {last_error}")

            # Read new lines from log
            lines = f.readlines()
            for line in lines:
                if "got signal" in line or "Assertion" in line or "Fatal" in line:
                    raise RuntimeError(f"MySQL crashed during startup:\n{line.strip()}")

            # Try connecting to MySQL
            try:
                subprocess.run(
                    [mysql_client, "-u", "root", f"--port={port}", "--protocol=tcp", "-e", "SELECT 1"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True
                )
                print("[INFO] mysqld is ready for queries.")
                return
            except subprocess.CalledProcessError as e:
                last_error = e.stderr.strip()
                # optional: print every few seconds
                if int(1 + time.time() - start_time) % 5 == 0:
                    print("[WAIT] MySQL not ready yet. Last error:", last_error)

            time.sleep(1)

def stop_mysqld(proc):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    print("[INFO] mysqld stopped.")


import mysql.connector
from mysql.connector import Error

def open_mysql_connection(host="127.0.0.1", port=3306, user="root", password="", database=None):
    """
    Open a MySQL connection and return it.
    """
    try:
        conn = mysql.connector.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            ssl_disabled=True
        )
        print("[INFO] MySQL connection established.")
        return conn
    except Error as e:
        raise RuntimeError(f"Failed to connect to MySQL: {e}")

def execute_query(conn, query, params=None):
    """
    Execute a SQL query on the given connection.
    Returns fetched results for SELECT, otherwise returns affected row count.
    """
    if conn is None or not conn.is_connected():
        raise RuntimeError("MySQL connection is not open.")

    cursor = conn.cursor()
    try:
        cursor.execute(query, params or ())
        if query.strip().lower().startswith("select"):
            result = cursor.fetchall()
        else:
            conn.commit()
            result = cursor.rowcount
        return result
    finally:
        cursor.close()

def close_mysql_connection(conn):
    """
    Close the given MySQL connection.
    """
    if conn is not None and conn.is_connected():
        conn.close()
        print("[INFO] MySQL connection closed.")
