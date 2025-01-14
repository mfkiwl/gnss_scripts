import time
import numpy as np
import pandas as pd
import os
import logging
import math
import datetime
from .gnss_time import GnssTime, hms2sod, sod2hms
from .constants import gns_name, leo_df


def read_site_list(f_list):
    """ read a site list file """
    try:
        with open(f_list) as f:
            lines = f.readlines()
            return [line[1:5].lower() for line in lines if line.startswith(' ')]
    except FileNotFoundError:
        logging.error("site_list not found")
        return


def read_sp3_file(f_sp3):
    start = time.time()
    try:
        with open(f_sp3) as f:
            lines = f.readlines()
    except FileNotFoundError:
        logging.warning(f"file not found {f_sp3}")
        return

    if len(lines) < 100:
        logging.warning(f"sp3 file too short ({len(lines)}")
        return

    try:
        nsat = int(lines[2][1:6])
    except ValueError:
        logging.warning(f"cannot get nsat in sp3: {lines[2]}")
        return

    # delete Velocities
    lines = [ln for ln in lines if ln[0] != 'V']
    # sp3 = [j.replace('P  ', 'PG0') for j in sp3]
    # sp3 = [j.replace('P ', 'PG') for j in sp3]

    data = []
    # header = ['time', 'sod', 'sat', 'px', 'py', 'pz']
    epoch = GnssTime(58849, 0)
    for line in lines:
        if not line or line.startswith('EOF'):
            break
        if line.startswith('*'):
            year, month, day, hh, mm, ss = line[1:].split()
            epoch = GnssTime.from_ymd(int(year), int(month), int(day),
                                      hms2sod(int(hh), int(mm), float(ss)))
            continue
        if not line.startswith('P'):
            continue
        sat, px, py, pz, *_ = line[1:].split()
        data.append({
            'epoch': epoch.fmjd, 'sod': epoch.sod, 'sat': sat,
            'px': float(px) * 1000, 'py': float(py) * 1000, 'pz': float(pz) * 1000
        })

    # ------------------------------------------------------------------
    end = time.time()
    msg = f"{f_sp3} file is read in {end - start:.2f} seconds"
    logging.info(msg)
    return pd.DataFrame(data)


def read_rnxc_file(f_name, mode="AS"):
    if not os.path.isfile(f_name):
        logging.error(f"file not found {f_name}")
        return

    data = []
    mode = mode + ' '
    with open(f_name) as f:
        for line in f:
            if line[0:3] != mode:
                continue
            if len(line) < 59:
                continue
            name = line[3:7].strip()
            year = int(line[8:12])
            mon = int(line[13:15])
            dd = int(line[16:18])
            sod = int(line[19:21]) * 3600 + int(line[22:24]) * 60 + float(line[25:34])
            epoch = GnssTime.from_ymd(year, mon, dd, sod)
            value = float(line[37:59])
            sat_dict = {'epoch': epoch.mjd + epoch.sod / 86400.0, 'sod': sod, 'name': name, 'clk': value}
            data.append(sat_dict)

    return pd.DataFrame(data)


def read_rnxo_file(f_name):
    start = time.time()
    if not os.path.isfile(f_name):
        logging.error(f"NO RINEXO file {f_name}")
        return

    obs_type = {}
    with open(f_name) as file_object:
        lines = file_object.readlines()

    # read rnxo header
    nline = 0
    for line in lines:
        if line.find("END OF HEADER") == 60:
            nline += 1
            break
        elif line.find("SYS / # / OBS TYPES") == 60:
            ot = line[0:60].split()
            ot_num = int(ot[1])
            ot_one = ot[2:]
            nline += 1
            if ot_num > 13:
                for _ in range(int(math.ceil(ot_num / 13)) - 1):
                    ot_one.extend(lines[nline][0:60].split())
                    nline += 1
            obs_type[line[0]] = ot_one
        else:
            nline += 1
    del lines[0:nline]

    # read rnxo data
    data = []
    nline = 0
    while True:
        # =============================================================================
        while True:
            if 'COMMENT' in lines[0]:
                del lines[0]
                nline += 1
            elif 'APPROX POSITION XYZ' in lines[0]:
                del lines[0]
                nline += 1
            elif 'REC # / TYPE / VERS' in lines[0]:
                raise Warning("Receiver type is changed! | Exiting...")
            else:
                break
        # =============================================================================
        if lines[0][0] == ">":
            epochLine = lines[0][1:].split()
            if len(epochLine) == 8:
                epoch_year, epoch_month, epoch_day, epoch_hour, epoch_minute, epoch_second, epoch_flag, epoch_sat_num = \
                    lines[0][1:].split()
                #receiver_clock = 0
            elif len(epochLine) == 9:
                epoch_year, epoch_month, epoch_day, epoch_hour, epoch_minute, epoch_second, epoch_flag, epoch_sat_num, _ = \
                    lines[0][1:].split()
            else:
                raise Warning("Unexpected epoch line format detected! | Program stopped!")
        else:
            raise Warning("Unexpected format detected! | Program stopped!")
        # =========================================================================
        if epoch_flag in {"1", "3", "5", "6"}:
            raise Warning("Deal with this later!")
        elif epoch_flag == "4":
            del lines[0]
            while True:
                if 'COMMENT' in lines[0]:
                    print(lines[0])
                    del lines[0]
                    nline += 1
                elif 'SYS / PHASE SHIFT' in lines[0]:
                    del lines[0]
                    # line += 1
                else:
                    break
        else:
            # =========================================================================
            sod = int(epoch_hour) * 3600 + int(epoch_minute) * 60 + float(epoch_second)
            epoch = GnssTime.from_ymd(int(epoch_year), int(epoch_month), int(epoch_day), sod)
            del lines[0]  # delete epoch header line
            # =============================================================================
            epoch_sat_num = int(epoch_sat_num)
            for svLine in range(epoch_sat_num):
                sat = lines[svLine][0:3]
                sys_ot = obs_type[sat[0]]
                ot_num = len(sys_ot)
                epoch_obs = {'epoch': epoch.fmjd, 'sat': sat}
                for i in range(ot_num):
                    if sys_ot[i][0] != 'C' and sys_ot[i][0] != 'L':
                        continue
                    if isfloat(lines[svLine][3 + 16 * i:16 * i + 17]):
                        epoch_obs[sys_ot[i]] = float(lines[svLine][3 + 16 * i:16 * i + 17])
                data.append(epoch_obs)

            # =============================================================================
            del lines[0:epoch_sat_num]  # number of rows in epoch equals number of visible satellites in RINEX 3
        if len(lines) == 0:
            break

    end = time.time()
    msg = f"{f_name} file is read in {end - start:.2f} seconds"
    logging.info(msg)
    return pd.DataFrame(data)


def read_res_file(f_res):
    try:
        with open(f_res) as file_object:
            lines = file_object.readlines()
    except FileNotFoundError:
        logging.warning(f"file not found {f_res}")
        return

    lfound = False
    line = ''
    for line in lines:
        if not line[0:2].startswith('##'):
            break
        if line.startswith('##Time&Interval'):
            lfound = True
            break

    if not lfound or len(line) < 62:
        logging.warning(f"Cannot find ##Time&Interval in {f_res}")
        return

    tbeg = GnssTime.from_str(line[28:47])
    intv = int(line[47:62])

    data = []
    for line in lines:
        if line.find("RES") != 0:
            continue
        tt = GnssTime.from_str(line[11:30])
        epo = int(tt.diff(tbeg) / intv) + 1
        data.append({
            'epo': epo, 'mjd': tt.fmjd, 'sod': tt.sod,
            'site': line[39:43], 'sat': line[48:51], 'ot': line[51:59].strip(),
            'res': float(line[74:89]), 'wgt': float(line[60:74])
        })
    return pd.DataFrame(data)


def read_clkdif_sum(f_name, mjd, ref_sat=""):
    try:
        with open(f_name) as f:
            lines = f.readlines()
    except FileNotFoundError:
        logging.error(f"file not found {f_name}")
        return

    sats = []
    str_val = ''
    for line in lines:
        if line[0:4] == 'NAME':
            sats = line[4:].replace('\n', '').rstrip().split()
        if line[0:3] == 'STD':
            str_val = line[4:].replace('\n', '')

    if not sats or not str_val:
        return pd.DataFrame()

    info = str_val.split()
    data = []
    for i in range(len(sats)):
        data.append({
            'sat': sats[i], 'gsys': gns_name(sats[i][0]), 'val': float(info[i]), 'mjd': int(mjd)
        })
    dd = pd.DataFrame(data)
    # find ref clock
    if not ref_sat:
        for sat in ['G01', 'G08', 'G05', 'E01', 'E02', 'C21', 'C22', 'C23', 'C24', 'C08', 'R01', 'R02']:
            if sat in set(dd.sat):
                ref_sat = sat
                break
    dd = dd[(dd.sat != ref_sat) & (dd['val'] < 3)]
    return dd


def read_time_info_new(file):
    try:
        with open(file) as file_object:
            lines = file_object.readlines()
    except FileNotFoundError:
        logging.warning(f"file not found {file}")
        return

    data = []
    for line in lines:
        if not line.startswith('Time for Processing epoch'):
            continue
        tt = GnssTime.from_str(line[27:46])
        hh, mm, ss = sod2hms(tt.sod)
        mss = int((tt.sod - int(tt.sod)) * 1000)
        crt_date = datetime.datetime(tt.year, tt.month, tt.day, hh, mm, ss, mss)
        data.append({
            'mjd': tt.fmjd, 'sod': tt.sod, 'date': crt_date, 'time': float(line[55:65]), 'nrec': int(line[92:95]),
            'nobs': int(line[115:123])
        })

    return pd.DataFrame(data)

def sum_clkdif(f_list, mjds, mode=None):
    if not f_list:
        logging.error(f"input clkdif file list is empty")
        return
    if len(f_list) != len(mjds):
        logging.error(f"mjd is required for summarizing clkdif")
        return
    data = pd.DataFrame()
    for i in range(len(f_list)):
        data_tmp = read_clkdif_sum(f_list[i], mjds[i])
        if data_tmp is None:
            continue
        else:
            if data_tmp.empty:
                continue
        data = data.append(data_tmp)

    sats = list(set(data.sat))
    sats.sort()
    ndays = len(mjds)
    if mode == 'sat':
        data_new = []
        for sat in sats:
            dd = data[data.sat == sat]
            if len(dd) < ndays * 0.6:
                continue
            data_new.append({
                'sat': sat, 'gsys': gns_name(sat[0]), 'val': dd['val'].mean()
            })
        return pd.DataFrame(data_new)
    elif mode == 'mjd':
        data_new = []
        gsys = list(set(data.gsys))
        gsys.sort()
        for mjd in mjds:
            for gs in gsys:
                dd = data[(data.mjd == mjd) & (data.gsys == gs)]
                data_new.append({
                    'mjd': mjd, 'gsys': gs, 'val': dd['val'].mean()
                })
        return pd.DataFrame(data_new)
    else:
        return data


def read_orbdif_sum(f_name):
    try:
        with open(f_name) as f:
            lines = f.readlines()
    except FileNotFoundError:
        logging.error(f"file not found {f_name}")
        return

    sats = []
    i = 0
    for line in lines:
        i += 1
        if line[0:19] == '                SAT':
            sats = line[27:].replace('\n', '').rstrip().split('               ')
            break

    if not sats:
        logging.error(f"not satellite in {f_name}")
        return

    del lines[0:i]
    nsats = len(sats)

    data = []
    mjd0 = 0
    sod0 = 0
    for line in lines:
        if line[0:3] == 'ACR':
            mjd0 = float(line[4:9])
            sod0 = float(line[10:19])
            break

    if mjd0 == 0:
        return
    mjd = mjd0 + sod0/86400
    str_rms = ''
    for line in lines:
        if line[0:6] == 'FITRMS':
            str_rms = line[19:].replace('\n', '')
            break

    if not str_rms:
        return

    for i in range(nsats):
        str_a = str_rms[i * 18:i * 18 + 6].strip()
        str_c = str_rms[i * 18 + 7:i * 18 + 12].strip()
        str_r = str_rms[i * 18 + 13:i * 18 + 18].strip()
        val_a = int(str_a) / 10  # unit: cm
        val_c = int(str_c) / 10
        val_r = int(str_r) / 10
        val_3d = math.sqrt(val_a ** 2 + val_c ** 2 + val_r ** 2)
        if val_3d > 200:
            continue
        data.append({'mjd': mjd, 'sat': sats[i], 'val': val_a, 'type': 'along'})
        data.append({'mjd': mjd, 'sat': sats[i], 'val': val_c, 'type': 'cross'})
        data.append({'mjd': mjd, 'sat': sats[i], 'val': val_r, 'type': 'radial'})
        data.append({'mjd': mjd, 'sat': sats[i], 'val': val_3d, 'type': '3d'})
    return pd.DataFrame(data)


def read_orbdif_file(f_name):
    try:
        with open(f_name) as f:
            lines = f.readlines()
    except FileNotFoundError:
        logging.error(f"file not found {f_name}")
        return

    sats = []
    i = 0
    for line in lines:
        i += 1
        if line[0:19] == '                SAT':
            sats = line[27:].replace('\n', '').rstrip().split('               ')
            break

    if not sats:
        logging.error(f"not satellite in {f_name}")
        return

    del lines[0:i]
    nsats = len(sats)

    data = []
    mjd0 = 0
    sod0 = 0
    for line in lines:
        if line[0:3] == 'ACR':
            mjd = float(line[4:9])
            sod = float(line[10:19])
            if mjd0 == 0 and sod0 == 0:
                mjd0 = mjd
                sod0 = sod
            sec = (mjd - mjd0)*86400 + sod - sod0
            fmjd = mjd + sod/86400
            str_rms = line[19:]
            for i in range(nsats):
                str_a = str_rms[i * 18:i * 18 + 6].strip()
                str_c = str_rms[i * 18 + 7:i * 18 + 12].strip()
                str_r = str_rms[i * 18 + 13:i * 18 + 18].strip()
                val_a = int(str_a) / 10  # unit: cm
                val_c = int(str_c) / 10
                val_r = int(str_r) / 10
                val_3d = math.sqrt(val_a ** 2 + val_c ** 2 + val_r ** 2)
                if val_3d > 200:
                    continue
                data.append({'mjd': fmjd, 'sec': sec, 'sat': sats[i], 'val': val_a, 'type': 'along'})
                data.append({'mjd': fmjd, 'sec': sec, 'sat': sats[i], 'val': val_c, 'type': 'cross'})
                data.append({'mjd': fmjd, 'sec': sec, 'sat': sats[i], 'val': val_r, 'type': 'radial'})
                data.append({'mjd': fmjd, 'sec': sec, 'sat': sats[i], 'val': val_3d, 'type': '3d'})

    if data:
        return pd.DataFrame(data)
    else:
        return


def sum_orbdif(f_list, mode=None):
    if not f_list:
        return
    data_sum = []
    for file in f_list:
        data_tmp = read_orbdif_sum(file)
        if data_tmp is None:
            continue
        else:
            if data_tmp.empty:
                continue
        mjd = int(data_tmp.mjd[0])
        sats = list(set(data_tmp.sat))
        sats.sort()
        for sat in sats:
            data_a = data_tmp[(data_tmp.sat == sat) & (data_tmp['type'] == 'along')]
            if 230 > len(data_a) > 1:
                continue
            for tp in ['along', 'cross', 'radial', '3d']:
                data = data_tmp[(data_tmp.sat == sat) & (data_tmp['type'] == tp)]
                data_sum.append({
                    'mjd': mjd, 'sat': sat, 'gsys': gns_name(sat[0]), 'rms': rms_val(data['val']), 'type': tp
                })
    data_pd = pd.DataFrame(data_sum)
    sats = list(set(data_pd.sat))
    sats.sort()
    mjds = list(set(data_pd.mjd))
    ndays = len(mjds)
    if mode == 'sat':
        data_new = []
        for sat in sats:
            dd = data_pd[data_pd.sat == sat]
            if len(dd) < ndays * 0.6 * 4:
                continue
            for tp in ['along', 'cross', 'radial', '3d']:
                dd = data_pd[(data_pd.sat == sat) & (data_pd.type == tp)]
                data_new.append({
                    'sat': sat, 'gsys': gns_name(sat[0]), 'rms': dd.rms.mean(), 'type': tp
                })
        return pd.DataFrame(data_new)
    elif mode == 'mjd':
        data_new = []
        gsys = list(set(data_pd.gsys))
        gsys.sort()
        for mjd in mjds:
            for gs in gsys:
                for tp in ['along', 'cross', 'radial', '3d']:
                    dd = data_pd[(data_pd.mjd == mjd) & (data_pd.gsys == gs) & (data_pd['type'] == tp)]
                    data_new.append({
                        'mjd': mjd, 'gsys': gs, 'rms': dd.rms.mean(), 'type': tp
                    })
        return pd.DataFrame(data_new)
    else:
        return data_pd


def rms_val(x):
    return math.sqrt(np.dot(x,x)/len(x))


def isfloat(value):
    """ To check if any variable can be converted to float or not """
    try:
        float(value)
        return True
    except ValueError:
        return False


def isint(value):
    """ To check if any variable can be converted to integer """
    try:
        int(value)
        return True
    except ValueError:
        return False


def check_ambflag(f_ambflag, nobs=1000):
    """ check if the ambflag file is correct"""
    try:
        with open(f_ambflag) as f:
            lfound = False
            num = 0
            for line in f:
                if line[0:23] == '%Available observations':
                    num = int(line[27:38])
                if line[0:3] == "AMB" or line[0:3] == "IAM":
                    lfound = True
                    break
            if not lfound:
                logging.warning(f"no valid ambiguity in {f_ambflag}")
            else:
                if num < nobs:
                    logging.warning(f"too few obs in {f_ambflag}: {num:8d}")
                    lfound = False
            return lfound
    except FileNotFoundError:
        return False


def switch_ambflag(config, old='AMB ', new='IAM ', mode='123'):
    if '2' in mode:
        f_ambflag = config.get_filename('ambflag', check=True)
        for f_name in f_ambflag.split():
            alter_file(f_name, old, new)
    if '3' in mode:
        f_ambflag = config.get_filename('ambflag13', check=True)
        for f_name in f_ambflag.split():
            alter_file(f_name, old, new)
    if '4' in mode:
        f_ambflag = config.get_filename('ambflag14', check=True)
        for f_name in f_ambflag.split():
            alter_file(f_name, old, new)
    if '5' in mode:
        f_ambflag = config.get_filename('ambflag15', check=True)
        for f_name in f_ambflag.split():
            alter_file(f_name, old, new)


def conv_ambflag_all(old_dir, new_dir):
    if not os.path.isdir(old_dir):
        logging.error(f"path not exists {old_dir}")
        return
    if not os.path.isdir(new_dir):
        os.makedirs(new_dir)
    num = 0
    for file in os.listdir(old_dir):
        n = len(file)
        if n < 7:
            continue
        if file[n-5: n] == "o.log" or file[n-7: n] in ["o.log13", "o.log14", "o.log15"]:
            file_new = os.path.join(new_dir, file)
            conv_ambflag_panda2great(os.path.join(old_dir, file), file_new)
            num += 1
    logging.info(f"{num} ambflag files are converted to GREAT format")


def conv_ambflag_panda2great(file, file_new):
    try:
        with open(file) as f:
            lines = f.readlines()
    except FileNotFoundError:
        logging.warning(f"file not found {file}")
        return
    # get ambflag header
    file_data = ""
    data = []
    for line in lines:
        if line[0] == '%':
            file_data += line
        elif line[0:3] in ['IAM', 'AMB', 'DEL', 'BAD']:
            data.append({'sat': line[4:7], 'iepo': int(line[7:14]), 'jepo': int(line[14:21]),
                         'flag': line[0:3], 'other': line[21:]})

    df = pd.DataFrame(data)
    df = df.sort_values(by=['sat', 'iepo'])
    for _, row in df.iterrows():
        file_data += f"{row['flag']} {row['sat']}{row['iepo']:>7d}{row['jepo']:>7d}{row['other']}"
    with open(file_new, 'w') as f:
        f.write(file_data)


def clean_ambflag(f_name, data):
    try:
        with open(f_name) as f:
            lines = f.readlines()
    except FileNotFoundError:
        logging.warning(f"file not found {f_name}")
        return

    file_data = ""
    for line in lines:
        if line[0] == '%':
            file_data += line
        elif line[0:3] in ['AMB', 'DEL', 'BAD']:
            file_data += line
        elif line[0:3] == 'IAM':
            sat = line[4:7]
            iepo = int(line[7:14])
            jepo = int(line[14:21])
            x = data[(data.sat == sat) & (data.iepo * 10 > iepo - 9) & (data.jepo * 10 < jepo + 10)]
            if not x.empty:
                line = line.replace('IAM', 'AMB')
                file_data += line
            else:
                file_data += line

    if not os.path.isfile(f"{f_name}.bak"):
        os.rename(f_name, f"{f_name}.bak")
    with open(f_name, 'w') as f:
        f.write(file_data)


def check_rnxo_ant(f_rnxo, f_atx, change=True):
    """ check if the antenna of RINEXO file in igs14.atx """
    if not os.path.isfile(f_rnxo):
        logging.warning(f"rinexo file not found {f_rnxo}")
        return False
    if not os.path.isfile(f_atx):
        logging.warning(f"atx file not found {f_atx}")
        return False

    rnxo_ant = ""
    with open(f_rnxo) as f:
        for line in f:
            if line.find("ANT #") == 60:
                rnxo_ant = line[20:40]
                break
            if line.find("END OF HEADER") > 0:
                logging.warning(f"cannot find ANT # in RINEXO file {f_rnxo}")
                return False
    if not rnxo_ant:
        logging.warning(f"cannot find ANT # in RINEXO file {f_rnxo}")
        return False

    atx_ant = ""
    with open(f_atx) as f:
        for line in f:
            if line[0:16] == rnxo_ant[0:16]:
                atx_ant = line[0:20]
                break
    if not atx_ant:
        logging.warning(f"cannot find {rnxo_ant[0:16].rstrip()} in {f_atx}")
        return False

    if rnxo_ant != atx_ant:
        if not change:
            logging.warning(f"rinexo antenna '{rnxo_ant}' differ with '{atx_ant}'")
            return False
        logging.info(f"convert rinexo ant from '{rnxo_ant}' to '{atx_ant}'")
        alter_file(f_rnxo, rnxo_ant, atx_ant, count=1)
        return True
    return True


def check_att_file(f_att):
    """ modify the attitude file header """
    sat = os.path.basename(f_att).split('_')[-1]
    if not sat.lower() in list(leo_df.svn):
        logging.warning(f"Unknown LEO satellite {sat} in att file name")
        return False
    if os.path.isfile(f_att):
        with open(f_att) as file_object:
            lines = file_object.readlines()
        pos = 0
        for i in range(len(lines)):
            if lines[i][0] == '%':
                continue
            pos = i
            break
        del lines[0:pos]
        if len(lines) < 100:
            logging.warning(f"records in attitude file too few: {len(lines)}")
            return False
        first = GnssTime(int(lines[0].split()[0]), float(lines[0].split()[1]))
        second = GnssTime(int(lines[1].split()[0]), float(lines[1].split()[1]))
        third = GnssTime(int(lines[2].split()[0]), float(lines[2].split()[1]))
        last = GnssTime(int(lines[-1].split()[0]), float(lines[-1].split()[1]))
        dt1 = second.diff(first)
        dt2 = third.diff(second)
        if dt1 - dt2 < 0.001:
            interval = int((dt1 + dt2)/2)
        else:
            logging.warning(f"cannot get the interval of att file: {dt1} != {dt2}")
            return False
        with open(f_att, "w") as file_object:
            file_object.write("%% Header of attitude data for LEO satellite\n")
            file_object.write(f"% Satellite     {sat.upper()}\n")
            file_object.write(f"% Start time   {int(first.mjd):>5d}   {first.sod:>12.5f}\n")
            file_object.write(f"% End time     {int(last.mjd):>5d}   {last.sod:>12.5f}\n")
            file_object.write(f"% Time interval {interval:>5.1f}\n")
            file_object.write("%% End of Header\n")
            file_object.writelines(lines)
        return True
    else:
        logging.warning(f"attitude file not found: {f_att}")
        return False


def alter_file(file, old_str, new_str, count=0):
    if not os.path.isfile(file):
        logging.warning(f"file not found {file}")
        return
    with open(file, "r", encoding="utf-8") as file_object:
        data = file_object.read()
    with open(file, "w", encoding="utf-8") as file_object:
        if count > 0:
            file_object.write(data.replace(old_str, new_str, count))
        else:
            file_object.write(data.replace(old_str, new_str))


def alter_file_content(file, old_str, new_str, end="", count=0):
    """
    Purpose: sed -i "s/old_str/new_str/g" file
    :param count: substitute each line until "count" times
    :param end: substitute each line until containing "end"
    :param file: Input file name
    :param old_str: old string
    :param new_str: new string
    :return:
    """
    file_data = ""
    is_end = False
    num = 0
    with open(file, "r", encoding="utf-8") as f:
        for line in f:
            if not is_end:
                if end:
                    if end in line:
                        is_end = True
                if count > 0:
                    if num >= count:
                        is_end = True
            if old_str in line and not is_end:
                line = line.replace(old_str, new_str)
                num += 1
            file_data += line
    with open(file, "w", encoding="utf-8") as f:
        f.write(file_data)
