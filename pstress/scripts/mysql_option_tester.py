#!/bin/python

"""
mysql_option_tester.py

This Python script automates testing MySQL startup options.

It reads a text file containing MySQL command-line options and tests each set
individually. For every option line, it:

1. Creates a temporary copy of the MySQL data directory.
2. Starts a MySQL server with the given options.
3. Waits for the server to become available or crash.
4. Optionally runs test SQL statements to validate basic functionality.
5. Shuts down the server and captures errors from the MySQL error log.

Filtered error messages are written to an output file alongside the tested options,
allowing quick identification of invalid or problematic configurations.
"""

import os
import argparse
from mysql_utils import *

def filter_log_file(input_file: str, output_fh):
    """
    Reads a log file, filters out lines containing [Warning] or [System],
    and writes the remaining lines to the provided open file handle.

    :param input_file: Path to the input log file.
    :param output_fh: Open file handle to write filtered lines.
    """
    with open(input_file, "r") as fh:
        for line in fh:
            if "[Warning]" not in line and "[System]" not in line:
                output_fh.write(line)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start MySQL with RocksDB, run SQL file, stop MySQL.")
    parser.add_argument("--basedir", required=True, help="MySQL base directory")
    parser.add_argument("--datadir", required=True, help="Path to MySQL data directory")
    parser.add_argument("--port", type=int, default=3307, help="Port for MySQL (default: 3307)")
    parser.add_argument("--host", default="127.0.0.1", help="MySQL base directory")
    parser.add_argument("--input-file", required=True, help="Path to text file with mysql options")
    parser.add_argument("--init", action="store_true", help="Create a new datadir (default: False)")

    args = parser.parse_args()

    base_name = os.path.splitext(os.path.abspath(args.input_file))[0]
    args.datadir = args.datadir.rstrip("/")
    temp_datadir = args.datadir + "_temp"
    err_log = f"{base_name}.log"
    output_file = f"{base_name}.out"

    mysqld_path = find_mysqld(args.basedir)
    if args.init:
        init_datadir(mysqld_path, args.basedir, args.datadir, err_log)

    with open(args.input_file, "r") as infile, open(output_file, "w") as outfile:
        for line in infile:
            commands = line.strip()
            if not commands:
                continue  # skip blank lines

            outfile.write(commands + "\n")
            conn = None  # Initialize the variable

            try:
                copy_datadir(args.datadir, temp_datadir)
                proc = start_mysqld(mysqld_path, args.basedir, temp_datadir, args.port, err_log, commands)

                #wait_for_mysql(args.basedir, args.port)
                wait_for_mysql_or_crash(args.basedir, args.port, err_log)
                conn = open_mysql_connection(port=args.port)
                if not args.init:
                    # Execute queries
                    execute_query(conn, "CREATE DATABASE IF NOT EXISTS test")
                    execute_query(conn, "USE test")
                    execute_query(conn, "DROP TABLE IF EXISTS opt_tester")
                    execute_query(conn, "CREATE TABLE opt_tester ( \
                        `ipkey` int NOT NULL AUTO_INCREMENT,    \
                        `d1` double DEFAULT NULL,               \
                        `t2` tinyint(1) DEFAULT NULL,           \
                        `i3` int DEFAULT NULL,                  \
                        PRIMARY KEY (`ipkey`),                  \
                        KEY `tt_10i1` (`ipkey`),                \
                        KEY `tt_10i0` (`d1`)                    \
                        ) ENGINE=ROCKSDB AUTO_INCREMENT=9493 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=REDUNDANT")
                    execute_query(conn, "INSERT INTO opt_tester (`d1`, `i3`, `ipkey`, `t2`) VALUES ('0.29463', '26', '88', '0')")
                    execute_query(conn, "INSERT INTO opt_tester (`d1`, `i3`, `ipkey`, `t2`) VALUES ('0.50208', '52', '195', '1')")
                    execute_query(conn, "INSERT INTO opt_tester (`d1`, `i3`, `ipkey`, `t2`) VALUES ('0.83123', '32', '321', '1')")
                    rows = execute_query(conn, "SELECT * FROM opt_tester WHERE ipkey=195")
                    print(rows)
            except Exception as e:
                print("[ERROR] MySQL setup failed:", e)
            finally:
                if conn:
                    close_mysql_connection(conn)
                stop_mysqld(proc)
                filter_log_file(err_log, outfile)
                outfile.flush()
                os.remove(err_log)
