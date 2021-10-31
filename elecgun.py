# -*- coding: utf-8 -*-
import socket
import time
import redis
import sqlite3
import json
import datetime
import os
import logging
from getconf import get_conf

filepath = "elec_logs"
filename = filepath + "\\" + datetime.datetime.now().strftime("%Y%m%d") + ".log"

if not os.path.exists(filepath):
    os.makedirs(filepath)

logging.basicConfig(level=logging.WARNING,
                    format='%(asctime)s %(filename)s[line:%(lineno)d] %(levelname)s %(message)s',
                    datefmt='%a, %d %b %Y %H:%M:%S', filename='%s' % filename, filemode='w')


class ConnectElecGun:
    def __init__(self, host="146.91.112.216", port=4545):
        self.sock = socket.socket()
        self.sock.connect((host, port))
        # 根据状态来判断当前的操作， 0：第一次开启，1：standby， 2：injob, 3:getpart, 4:jobdone
        # 5：返松 freemode，6：手动job1，7：手动job2, 8: 关闭
        self.status = None
        self.stopflash = None
        self.esn = '        '
        self.rd = redis.Redis()
        self.stop_thread = 0
        self.ledon = None
        self.jobnum = None
        # self.type = None
        self.recv = None
        self.ledoff_count = 3
        self.ledon_count = 3
        self.last_comm = None

    def sendAlive(self):
        '''每隔5秒发送一次，确保连接OK'''
        while 1:
            if self.stop_thread == 1:
                # self.sock.sendall(b'00200044001         0')
                break
            try:
                self.sock.sendall(b'00209999000         0')
                time.sleep(2)
            except Exception as e:
                print('alive', e)
                logging.error('alive error: %s' % str(e))
                gun_dis_data = {'connect': 'disconnect'}
                self.rd.publish('connect', json.dumps(gun_dis_data))
                break

    def disconnect(self):
        self.sock.close()
        # self.cur.close()
        # self.conn.close()

    def listenallrecv(self):
        self.status = 0  # 首次启动
        self.sock.sendall(b"00200001003         0")  # 启动1， mid0001表示发送连接请求
        print('--------connect----------')
        while 1:
            try:
                data = self.sock.recv(1024).decode()
                if data:
                    print(data)
            except Exception as e:
                print('监听电枪返回的信息', e)
                logging.error('监听电枪返回的信息,%s' % str(e))
                break

            if data[4:8] == '0002':  # 返回mid0002，表示已经连接

                # 启动2，mid0127表示先jobabort，abort以前的job
                self.sock.sendall(b"00200127000         0")

            elif data[4:8] == '0004':
                print('connect error')
                logging.error('command error 0004')
                logging.error('data detail: %s' % str(data))
                if len(data) >= 24:
                    if data[20:24] == "0200" and self.ledoff_count >= 1 and self.last_comm == '00300200000         00000000001':
                        time.sleep(0.2)
                        logging.error('led off send count:%s' %
                                      str(self.ledoff_count))
                        self.sock.sendall(b'00300200000         00000000001')
                        self.ledoff_count = self.ledoff_count - 1
                    elif data[20:24] == "0200" and self.ledon_count >= 1 and "1" in self.last_comm[20:24]:
                        time.sleep(0.2)
                        logging.error('led on send count:%s' %
                                      str(self.ledon_count))
                        self.sock.sendall(self.last_comm.encode())
                        self.ledon_count = self.ledon_count - 1

            elif data[4:8] == '0005':

                if data[20:24] == '0127':
                    if self.status == 0:
                        # 启动3，mid0042表示distool
                        self.sock.sendall(b"00200042001         0")
                    elif self.status == 2:
                        # 作业3， 发送mid0043，enabletool
                        self.sock.sendall(b"00200043001         0")
                    elif self.status == 8:  # 退出时，jobabort，distool，ledsoff
                        self.sock.sendall(b'00200042001         0')

                elif data[20:24] == '0042':
                    if self.status == 0:
                        # 启动4 mid0130表示joboff 第20位 0： set job off  1: reset job  off
                        self.sock.sendall(b"00210130000         10")
                    elif self.status == 8:
                        self.sock.sendall(b"00300200000         00000000001")

                elif data[20:24] == '0130':
                    if self.status == 0:
                        # 启动5， mid0034表示jobsubs，订阅
                        self.sock.sendall(b"002000340000        0")

                elif data[20:24] == '0034':
                    # 启动6，mid0210表示订阅外部输入
                    self.sock.sendall(b"002002100001        0")

                elif data[20:24] == '0210':
                    # 启动7，关闭所有的led灯
                    self.sock.sendall(b"00300200000         00000000001")

                elif data[20:24] == '0200':
                    if self.status == 0:  # 启动8，更改状态，当前为启动，状态变为standby
                        self.status = 1
                    # elif self.status == 1:                          #当前状态为standby
                    # 	pass
                    elif self.status == 2:  # 作业2，状态为injob，发送mid0127，进行jobabort
                        self.sock.sendall(b"00200127000         0")

                elif data[20:24] == '0043':
                    if self.status == 2:  # 作业4，发送esn
                        sendesn = '00280150000         ' + self.esn + '0'
                        self.sock.sendall(sendesn.encode())

                    elif self.status == 5:
                        # 返松 freemode模式下，使用job3
                        self.sock.sendall(b"00220038001         030")

                elif data[20:24] == '0150':
                    if self.status == 2:
                        self.sock.sendall(self.jobnum.encode())

            elif data[4:8] == '0211':  # 取料2，外部的灯状态改变，也就是闪烁的料灯被触摸
                if self.status == 3:  # 取料状态

                    if data[20:24] == self.recv:
                        self.stopflash = 0

                        self.sock.sendall(self.ledon.encode())

            elif data[4:8] == '0035':  # 接受订阅信息
                # 发送mid0036，告知已经接收到了返回的订阅信息
                self.sock.sendall(b"00200036000         0")

                if self.status == 5:  # 如果是返松模式，不用处理
                    continue
                else:
                    result_ok = data[26]  # 返回的信息，当前枪打的是否合格
                    count_total = int(data[32:36])  # 本job的总次数
                    count_current = int(data[38:42])  # 当前的次数
                    # print(type(result_ok))
                    # 将结果发布到redis里面
                    pub_date = {'status': '2', 'esn': self.esn, 'part_type': self.curtype,
                                'total_count': count_total, 'current_count': count_current, 'result': result_ok}
                    print(pub_date)
                    self.rd.publish('gun_result', json.dumps(pub_date))
                    if count_current == count_total and result_ok == '1':
                        # self.status = 4 #设置状态完工。
                        self.status = 1  # 设置状态standby。

                        complete_data = {'esn': self.esn,
                                         'part_type': self.curtype}
                        self.rd.publish(
                            'complete_gun', json.dumps(complete_data))
                        # self.sock.sendall(b'00209999000         0')
                        # time.sleep(0.2)
                        self.last_comm = '00300200000         00000000001'
                        self.sock.sendall(b'00300200000         00000000001')
                        time.sleep(0.3)
                        self.sock.sendall(b'00200042001         0')

        print('电枪接收线程退出')

    def lightflash(self, n):
        # ledon = {'32':"00300200000         00100000001", '31':"00300200000         01000000001", '30':"00300200000         00010000001"}
        # ledoff = '00300200000         00000000001'
        # ledon_ = ledon[n]
        ledon_ = n
        # 让LED闪烁，满足条件时，退出循环
        while 1:
            if self.stopflash == 0:
                # self.sock.sendall(b'00209999000         0')
                # time.sleep(0.2)
                self.last_comm = ledon_
                self.status = 2
                self.sock.sendall(ledon_.encode())
                break
            self.sock.sendall(b'00300200000         00000000001')   # off led
            time.sleep(0.4)
            self.sock.sendall(ledon_.encode())  # on led
            time.sleep(0.4)

    def getmaterial(self, status, esn, ptype):
        # 设置为取料状态，
        print(self.status)
        self.status = status
        self.stopflash = 1
        # add by sunhx 2019/07/24, 3 new flags to deal with error 0004
        self.ledon_count = 3
        self.ledoff_count = 3
        self.last_comm = None

        self.esn = esn

        self.curtype = ptype
        esn_data = {'status': '1', 'esn': self.esn, 'ptype': self.curtype}
        self.rd.publish('sendesn', json.dumps(esn_data))

        conf_ = 'type_' + str(self.curtype)

        # 从配置文件读取当前类型的操作
        f = get_conf(conf_)
        # self.type = f['type']
        self.ledon = f['led']
        self.jobnum = f['job']
        self.recv = f['recv']

        if self.status == 3:
            self.lightflash(self.ledon)

    def freemode(self):
        self.status = 5
        self.sock.sendall(b"00200127000         0")  # 先jobabort
        self.sock.sendall(b"00200043001         0")   # enable tool

    # 已修改手动处理模式，目前为用到
    def handmode(self, esn, curtype):
        self.stopflash = 1
        self.status = 3
        self.esn = esn
        self.curtype = curtype

        conf_ = 'type_' + str(self.curtype)
        f = get_conf(conf_)

        self.ledon = f['led']
        self.jobnum = f['job']
        self.recv = f['recv']

        self.lightflash(self.ledon)

    def elecquit(self):
        self.status = 8
        self.sock.sendall(b'00200127000         0')
